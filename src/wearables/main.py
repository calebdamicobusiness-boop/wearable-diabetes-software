"""Run with:  python -m wearables.main   (from the src folder)"""
from wearables import config
from wearables.ingest.mock_source import MockSource
from wearables.pipeline import run


def main() -> None:
    readings, insights = run(MockSource())
    print(f"{len(readings)} time buckets, {len(insights)} insights\n")
    for i in insights:
        print(f"{i.timestamp:%H:%M}  [{i.kind}]  {i.message}")
    print(f"\n{config.DISCLAIMER}")


if __name__ == "__main__":
    main()
