import logging
import sys

from .sales_db import approve_followup, init_db, setup_tracing


def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print(
            "python -m sales_lead_agent_project.approve_followup "
            "<followup_id>"
        )
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    setup_tracing()
    init_db()

    followup_id = sys.argv[1]
    result = approve_followup(followup_id=followup_id)

    print(result)


if __name__ == "__main__":
    main()