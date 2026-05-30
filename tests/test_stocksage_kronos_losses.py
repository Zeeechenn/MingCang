import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

FINETUNE_DIR = Path(__file__).resolve().parents[1] / "vendor" / "kronos" / "finetune"
if str(FINETUNE_DIR) not in sys.path:
    sys.path.insert(0, str(FINETUNE_DIR))


def test_listmle_prefers_correct_cross_section_order_and_is_shift_invariant():
    from stocksage_losses import listmle_loss

    target_returns = torch.tensor([[0.30, 0.20, 0.10]])
    good_scores = torch.tensor([[3.0, 2.0, 1.0]])
    bad_scores = torch.tensor([[1.0, 2.0, 3.0]])

    good_loss = listmle_loss(good_scores, target_returns)
    shifted_loss = listmle_loss(good_scores + 10.0, target_returns)
    bad_loss = listmle_loss(bad_scores, target_returns)

    assert good_loss < bad_loss
    assert torch.allclose(good_loss, shifted_loss, atol=1e-6)


def test_path_a_loss_combines_rank_and_reconstruction_weights():
    from stocksage_losses import path_a_loss

    scores = torch.tensor([[2.0, 1.0]])
    returns = torch.tensor([[0.2, 0.1]])
    recon_pred = torch.tensor([[[1.0], [3.0]]])
    recon_target = torch.tensor([[[1.0], [1.0]]])

    breakdown = path_a_loss(
        predicted_scores=scores,
        target_returns=returns,
        reconstruction_prediction=recon_pred,
        reconstruction_target=recon_target,
        lambda_rank=0.7,
        lambda_recon=0.3,
    )

    assert torch.allclose(breakdown.total, 0.7 * breakdown.rank + 0.3 * breakdown.recon)
    assert breakdown.recon.item() == 2.0
