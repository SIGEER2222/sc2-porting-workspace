"""CLI wrapper for the P1 native replay imitation trainer."""

from .p1_ml import train_from_manual_replay

__all__ = ["train_from_manual_replay"]


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Train P1 PyTorch imitation policy")
    parser.add_argument("--observations", required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    result = train_from_manual_replay(args.observations, args.actions, args.checkpoint, args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
