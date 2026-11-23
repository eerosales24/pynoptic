"""Run every demonstration case and check each one fires the metric it is for.

This is not the test suite — that lives in ``tests/`` and runs in seconds.
This is the demonstration: seventeen exercises, one per metric, each
profiled exactly the way a real submission would be, with the verdict
checked against what the case says it should be.

    python demo/correr.py              # the table
    python demo/correr.py --detalle    # the full profile of every case
    python demo/correr.py M06          # one case, with its trace

A case passes when the metric it was written for comes back PRESENT *and*
resolved. Resolved matters as much as present: a candidate that nothing
settled is not a detection, and a demonstration that counted it as one
would be claiming the dynamic layer works without ever running it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "casos"

# Importable from a source checkout without installing.
sys.path.insert(0, str(ROOT.parent / "src"))

from pynoptic.metrics import Judgement, scan_metrics_file  # noqa: E402
from pynoptic.profile import Profile, profile_file  # noqa: E402


def cases(only: str | None = None) -> list[tuple[Path, dict[str, object]]]:
    """Return every case directory and its description.

    Parameters:
        - only: A metric id or directory prefix to filter by.

    Returns:
        - Pairs of (directory, caso.json contents), in catalog order.
    """
    found = []
    for directory in sorted(CASES.iterdir()):
        if not directory.is_dir():
            continue
        description = directory / "caso.json"
        if not description.exists():
            continue
        if only and not directory.name.upper().startswith(only.upper()):
            continue
        found.append((directory, json.loads(description.read_text(encoding="utf-8"))))
    return found


def run_case(
    directory: Path,
    caso: dict[str, object],
    *,
    trace: bool = False,
    ncc: bool = True,
) -> Profile:
    """Profile one case the way a real submission would be profiled.

    Parameters:
        - directory: The case directory.
        - caso: The parsed caso.json.
        - trace: Whether to record the ordered event log.
        - ncc: Whether to run the restriction catalog too. Leaving it out
          roughly halves the wall clock, because Semgrep's startup is most
          of it.

    Returns:
        - The profile.
    """
    return profile_file(
        directory / "submission.py",
        level=int(str(caso["nivel"])),
        function=str(caso["funcion"]),
        dynamic=True,
        driver=directory / "driver.py",
        timeout=60,
        trace=trace,
        ncc=ncc,
    )


def resultado_de(
    directory: Path, caso: dict[str, object], profile: Profile
) -> dict[str, object]:
    """Describe what one case's metric did, as JSON.

    The field that answers the question is ``activada``: true when the
    phenomenon the metric asks about is present in this submission. It is a
    statement about the code, not about whether the demonstration passed —
    "are there iterations with no effect here?" is true, and that is what
    the reader wants to know.

    Whether the case behaved as it was written to behave is a different
    question, and it lives under ``caso`` so the two cannot be confused.

    Parameters:
        - directory: The case directory.
        - caso: The parsed caso.json.
        - profile: The audit of that case.

    Returns:
        - The case's result, ready to serialise.
    """
    expected = str(caso["espera"])
    finding = profile.metrics.by_id(expected) if profile.metrics else None
    # A case may declare that no single run can settle its verdict, which is
    # true of exactly one metric: M13 needs several input sizes to name a
    # growth class. Saying so in the case is how the demonstration stays
    # honest instead of quietly counting a measurement as a detection.
    wants_resolved = bool(caso.get("espera_resuelto", True))

    activated = finding is not None and finding.verdict is Judgement.PRESENT
    resolved = bool(finding and finding.resolved)
    as_expected = activated and (resolved or not wants_resolved)

    detail: dict[str, object] = {
        "metrica": expected,
        "nombre": finding.metric.name if finding else "",
        "activada": activated,
        "resuelta": resolved,
        "decidida_por": finding.detector if finding else "",
        "lineas": sorted({e.line for e in finding.evidence}) if finding else [],
        "evidencia": [
            {
                "linea": e.line,
                "codigo": profile.line(e.line),
                "elemento": e.element,
                "porque": e.detail,
            }
            for e in (finding.evidence if finding else ())
        ],
        "observado_al_ejecutar": str(finding.data.get("runtime", "")) if finding else "",
        "caso": {
            "carpeta": directory.name,
            "nivel": int(str(caso["nivel"])),
            "funcion": str(caso["funcion"]),
            "esperaba_activarse": True,
            "esperaba_resolverse": wants_resolved,
            "coincide_con_lo_esperado": as_expected,
        },
    }
    if finding is None:
        detail["nota"] = f"{expected} no aplica en nivel {caso['nivel']}"
    elif not activated:
        detail["nota"] = f"veredicto {finding.verdict.value}"
    elif not resolved and wants_resolved:
        detail["nota"] = "quedo como candidato: nada lo decidio"
    return detail


def juzgar(selected: list[tuple[Path, dict[str, object]]]) -> int:
    """Check each case's example answer against its metric's contract.

    Every metric asks its judge for one JSON object of a fixed shape, and
    the point of the subsystem is that the detector and the judge speak that
    same vocabulary. This mode walks the whole loop for each case: it
    renders the prompt the judge would be sent, validates the example answer
    with the real validator, and lines it up against the detector.

    The answers are examples shipped with the cases, not a model's. They are
    here to prove the contract holds end to end for all three answer shapes,
    which is a claim about the format, not about any model's accuracy.

    Parameters:
        - selected: The cases to check.

    Returns:
        - 0 when every answer satisfied its schema.
    """
    from pynoptic.metrics import get_metric
    from pynoptic.metrics.llm import ExerciseSpec, InvalidAnswer, parse_answer, render_prompt
    from pynoptic.metrics.llm.compare import compare
    from pynoptic.metrics.llm.render import PROMPT_FIELDS

    filas: list[dict[str, object]] = []
    failures = 0
    for directory, caso in selected:
        expected = str(caso["espera"])
        metric = get_metric(expected)
        source = (directory / "submission.py").read_text(encoding="utf-8")

        spec = ExerciseSpec(
            statement=str(caso.get("descripcion", "")),
            level=int(str(caso["nivel"])),
        )
        prompt = render_prompt(metric, source, spec=spec)
        # The prompt's three guarantees, checked rather than assumed: the
        # numbered source, the schema, and both escape hatches.
        ok_prompt = (
            all("{" + field + "}" not in prompt for field in PROMPT_FIELDS)
            and "NO_APLICA" in prompt
            and "NO_DECIDIBLE" in prompt
        )

        answer_file = directory / "respuesta_ejemplo.json"
        if not answer_file.exists():
            filas.append(
                {
                    "metrica": expected,
                    "forma": metric.shape.value,
                    "esquema_valido": False,
                    "error": "no hay respuesta_ejemplo.json",
                }
            )
            failures += 1
            continue

        # Compared against the *resolved* report, not the static one. Nine
        # of the metrics are candidates until the submission runs, and
        # comparing a judge's verdict against a candidate can only ever come
        # back "not comparable" — which would say nothing about the judge.
        report = scan_metrics_file(
            directory / "submission.py",
            level=int(str(caso["nivel"])),
            function=str(caso["funcion"]),
            dynamic=True,
            driver=directory / "driver.py",
            timeout=60,
        )
        finding = report.by_id(expected)
        try:
            answer = parse_answer(
                metric,
                answer_file.read_text(encoding="utf-8"),
                line_count=len(source.splitlines()),
            )
        except InvalidAnswer as exc:
            filas.append(
                {
                    "metrica": expected,
                    "forma": metric.shape.value,
                    "esquema_valido": False,
                    "error": str(exc),
                }
            )
            failures += 1
            continue

        agreement = compare(metric, finding, answer) if finding else None
        filas.append(
            {
                "metrica": expected,
                "forma": metric.shape.value,
                "esquema_valido": True,
                "prompt_completo": ok_prompt,
                "juez": {
                    "veredicto": answer.verdict.value,
                    "lineas": [e.line for e in answer.evidence],
                    "n": answer.count,
                    "clase_estudiante": answer.student_class,
                    "clase_referencia": answer.reference_class,
                    "razon": answer.reason,
                },
                "detector": {
                    "veredicto": finding.verdict.value if finding else None,
                    "lineas": sorted({e.line for e in finding.evidence}) if finding else [],
                    "resuelto": bool(finding and finding.resolved),
                },
                "coinciden": agreement.agrees if agreement else None,
                "evidencia_se_solapa": agreement.evidence_overlap if agreement else None,
                "nota": agreement.note if agreement else "",
            }
        )
        if not ok_prompt:
            failures += 1

    total = len(selected)
    payload = {
        "resumen": {
            "casos": total,
            "respuestas_validas": total - failures,
            "coinciden": sum(1 for f in filas if f.get("coinciden") is True),
            "no_comparables": sum(1 for f in filas if f.get("coinciden") is None),
            "advertencia": (
                "Las respuestas son ejemplos que vienen con los casos, no de un modelo. "
                "Demuestran que el contrato cierra para las tres formas, no la precision "
                "de ningun modelo."
            ),
        },
        "casos": filas,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Run the demonstration.

    Parameters:
        - argv: Arguments to parse; defaults to the command line.

    Returns:
        - 0 when every case fired its metric, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrica", nargs="?", help="Solo este caso, por ejemplo M06")
    parser.add_argument("--detalle", action="store_true", help="Imprime el perfil completo")
    parser.add_argument(
        "--traza",
        action="store_true",
        help="Registra y muestra lo que hizo la corrida, en orden",
    )
    parser.add_argument(
        "--juez",
        action="store_true",
        help="Valida la respuesta de ejemplo de cada caso contra el esquema y la compara",
    )
    parser.add_argument(
        "--sin-ncc",
        dest="sin_ncc",
        action="store_true",
        help="Omite Semgrep, que es lo lento",
    )
    args = parser.parse_args(argv)

    selected = cases(args.metrica)
    if not selected:
        print(f"No hay casos que empiecen por {args.metrica!r}", file=sys.stderr)
        return 2

    if args.juez:
        return juzgar(selected)

    # A trace nobody prints is a trace nobody asked for: --traza implies the
    # full profile, which is where it is rendered.
    detailed = args.detalle or args.traza

    resultados = []
    for directory, caso in selected:
        profile = run_case(directory, caso, trace=args.traza, ncc=not args.sin_ncc)
        resultados.append(resultado_de(directory, caso, profile))
        if detailed:
            print(profile.render())
            print()

    activadas = sum(1 for r in resultados if r["activada"])
    como_esperado = sum(1 for r in resultados if r["caso"]["coincide_con_lo_esperado"])
    payload = {
        "resumen": {
            "casos": len(resultados),
            "activadas": activadas,
            "como_lo_esperaba_el_caso": como_esperado,
        },
        "casos": resultados,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if como_esperado == len(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
