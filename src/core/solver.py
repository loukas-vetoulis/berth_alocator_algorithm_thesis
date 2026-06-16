from __future__ import annotations
from .data_model import MarinaInstance, SolveResult
from .model_basic import solve_basic
from .model_extensions import solve_extended
from .model_temporal import solve_temporal


def solve(
    inst: MarinaInstance,
    mode: str = "basic",
    extensions: list[str] | None = None,
    allow_relocation: bool = False,
    max_relocations: int = 1,
    gap_discount_rate: float = 0.0,
    penalty_M: float = 1000.0,
    solver_name: str = "GLPK_MI",
    verbose: bool = False,
) -> SolveResult:
    ext = extensions or []

    if mode == "basic":
        return solve_basic(inst, solver=solver_name, verbose=verbose)

    if mode == "extended":
        return solve_extended(
            inst,
            use_compat="compat"     in ext,
            use_utility="utility"   in ext,
            use_vip="vip"           in ext,
            side_by_side="sbs"      in ext,
            soft_depth="soft"       in ext,
            penalty_M=penalty_M,
            solver=solver_name,
            verbose=verbose,
        )

    if mode == "temporal":
        return solve_temporal(
            inst,
            allow_relocation=allow_relocation,
            max_relocations=max_relocations,
            gap_discount_rate=gap_discount_rate,
            solver=solver_name,
            verbose=verbose,
        )

    raise ValueError(f"Unknown mode: {mode!r}. Choose 'basic', 'extended', or 'temporal'.")
