"""
CLI Interface (main.py)
Provides command-line commands for crawling dental practices by state,
exporting deduplicated data to CRM CSV, and inspecting database statistics.
"""

import argparse
import sys
from crawler import crawl_state
from database import export_to_crm_csv, get_stats, init_db


def main():
    parser = argparse.ArgumentParser(
        description="Modular State-by-State US Dentist Web Crawler & Extractor"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: crawl
    crawl_parser = subparsers.add_parser("crawl", help="Crawl dental practices for a target state")
    crawl_parser.add_argument(
        "--state",
        type=str,
        required=True,
        help="Target US State code (e.g., TX, FL, OH, CA, NY)",
    )
    crawl_parser.add_argument("--limit", type=int, default=1000, help="Number of practices to crawl")
    
    crawl_parser.add_argument(
        "--db",
        type=str,
        default="dentists.db",
        help="SQLite database path (default: dentists.db)",
    )
    crawl_parser.add_argument(
        "--delay-min",
        type=float,
        default=1.5,
        help="Minimum delay in seconds between HTTP requests (default: 1.5)",
    )
    crawl_parser.add_argument(
        "--delay-max",
        type=float,
        default=3.5,
        help="Maximum delay in seconds between HTTP requests (default: 3.5)",
    )

    # Command: export
    export_parser = subparsers.add_parser("export", help="Export stored dentist data to CRM CSV")
    export_parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Filter export by state code (e.g., TX). If omitted, exports all states.",
    )
    export_parser.add_argument(
        "--output",
        type=str,
        default="crm_export.csv",
        help="Output CSV filepath (default: crm_export.csv)",
    )
    export_parser.add_argument(
        "--db",
        type=str,
        default="dentists.db",
        help="SQLite database path (default: dentists.db)",
    )

    # Command: stats
    stats_parser = subparsers.add_parser("stats", help="Display database metrics and extraction statistics")
    stats_parser.add_argument(
        "--db",
        type=str,
        default="dentists.db",
        help="SQLite database path (default: dentists.db)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "crawl":
        print(f"=== US Dentist Crawler: Crawl Mode ===")
        crawl_state(
            state=args.state,
            limit=args.limit,
            db_path=args.db,
            verbose=True,
            delay_range=(args.delay_min, args.delay_max),
        )

    elif args.command == "export":
        print(f"=== US Dentist Crawler: Export Mode ===")
        rows_exported = export_to_crm_csv(
            state=args.state,
            output_path=args.output,
            db_path=args.db,
        )
        print(f"[+] Export Successful! {rows_exported} rows written to: {args.output}")

    elif args.command == "stats":
        print(f"=== US Dentist Crawler: Statistics ===")
        init_db(args.db)
        stats = get_stats(args.db)
        print(f"Database File: {args.db}")
        print(f"Total Practices Stored:       {stats['total_dentists']}")
        print(f"Practices with Extracted Owner: {stats['with_owner_extracted']} ({stats['owner_extraction_percentage']}%)")
        print("\nBreakdown by State:")
        if stats["state_breakdown"]:
            for st, count in stats["state_breakdown"].items():
                print(f"  - {st}: {count} practices")
        else:
            print("  (No data stored yet)")


if __name__ == "__main__":
    main()
