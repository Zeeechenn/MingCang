"""MingCang-owned M27.4 Path A losses for Kronos fine-tuning."""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F


@dataclass(frozen=True)
class PathALossBreakdown:
    total: torch.Tensor
    rank: torch.Tensor
    recon: torch.Tensor


def listmle_loss(
    predicted_scores: torch.Tensor,
    target_returns: torch.Tensor,
    mask: torch.Tensor | None = None,
) -> torch.Tensor:
    """ListMLE ranking loss over a batch of cross-sections.

    Higher target returns should rank ahead of lower target returns. The loss is
    invariant to adding a constant to every predicted score in a row.
    """
    if predicted_scores.shape != target_returns.shape:
        raise ValueError("predicted_scores and target_returns must have the same shape")
    if predicted_scores.ndim != 2:
        raise ValueError("ListMLE expects [batch, assets] tensors")

    if mask is None:
        mask = torch.ones_like(target_returns, dtype=torch.bool)
    else:
        mask = mask.to(dtype=torch.bool, device=target_returns.device)
        if mask.shape != target_returns.shape:
            raise ValueError("mask must have the same shape as targets")

    row_losses: list[torch.Tensor] = []
    for scores_row, targets_row, mask_row in zip(predicted_scores, target_returns, mask, strict=True):
        valid_scores = scores_row[mask_row]
        valid_targets = targets_row[mask_row]
        if valid_scores.numel() < 2:
            continue

        order = torch.argsort(valid_targets, descending=True, stable=True)
        ordered_scores = valid_scores[order]
        log_denom = torch.logcumsumexp(ordered_scores.flip(0), dim=0).flip(0)
        row_losses.append((log_denom - ordered_scores).sum())

    if not row_losses:
        return predicted_scores.new_tensor(0.0)
    return torch.stack(row_losses).mean()


def masked_reconstruction_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor | None = None,
) -> torch.Tensor:
    if prediction.shape != target.shape:
        raise ValueError("prediction and target must have the same shape")
    squared_error = (prediction - target) ** 2
    if mask is None:
        return F.mse_loss(prediction, target)

    mask = mask.to(dtype=torch.bool, device=prediction.device)
    while mask.ndim < squared_error.ndim:
        mask = mask.unsqueeze(-1)
    expanded = mask.expand_as(squared_error)
    if not torch.any(expanded):
        return prediction.new_tensor(0.0)
    return squared_error[expanded].mean()


def path_a_loss(
    *,
    predicted_scores: torch.Tensor,
    target_returns: torch.Tensor,
    reconstruction_prediction: torch.Tensor,
    reconstruction_target: torch.Tensor,
    rank_mask: torch.Tensor | None = None,
    reconstruction_mask: torch.Tensor | None = None,
    lambda_rank: float = 0.7,
    lambda_recon: float = 0.3,
) -> PathALossBreakdown:
    rank = listmle_loss(predicted_scores, target_returns, rank_mask)
    recon = masked_reconstruction_loss(
        reconstruction_prediction,
        reconstruction_target,
        reconstruction_mask,
    )
    total = lambda_rank * rank + lambda_recon * recon
    return PathALossBreakdown(total=total, rank=rank, recon=recon)
