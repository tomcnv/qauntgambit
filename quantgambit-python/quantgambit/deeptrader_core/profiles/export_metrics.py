"""
Profile Metrics Export Utility

Exports profile performance data to CSV and JSON formats for analysis.
"""

import csv
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

from quantgambit.deeptrader_core.profiles.profile_router import get_profile_router


class ProfileMetricsExporter:
    """
    Export profile performance metrics to various formats
    
    Supports:
    - CSV export for spreadsheet analysis
    - JSON export for programmatic access
    - Filtered exports by symbol, date range, performance
    """
    
    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.router = get_profile_router()
    
    def export_all_to_csv(self, filename: Optional[str] = None) -> str:
        """
        Export all profile metrics to CSV
        
        Args:
            filename: Optional custom filename
            
        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"profile_metrics_{timestamp}.csv"
        
        filepath = self.output_dir / filename
        
        # Get all metrics
        metrics = self.router.get_all_metrics()
        top_profiles = metrics.get('top_profiles', [])
        
        # Write CSV
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                'Profile ID',
                'Trades',
                'Win Rate (%)',
                'Avg PnL ($)',
                'Total PnL ($)',
                'Symbols'
            ])
            
            # Data rows
            for profile in top_profiles:
                writer.writerow([
                    profile.get('profile_id', ''),
                    profile.get('trades', 0),
                    f"{profile.get('win_rate', 0):.2f}",
                    f"{profile.get('avg_pnl', 0):.2f}",
                    f"{profile.get('total_pnl', 0):.2f}",
                    ', '.join(profile.get('symbols', []))
                ])
        
        print(f"✅ Exported to CSV: {filepath}")
        return str(filepath)
    
    def export_all_to_json(self, filename: Optional[str] = None) -> str:
        """
        Export all profile metrics to JSON
        
        Args:
            filename: Optional custom filename
            
        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"profile_metrics_{timestamp}.json"
        
        filepath = self.output_dir / filename
        
        # Get all metrics
        metrics = self.router.get_all_metrics()
        
        # Add metadata
        export_data = {
            'export_time': datetime.now().isoformat(),
            'metrics': metrics
        }
        
        # Write JSON
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✅ Exported to JSON: {filepath}")
        return str(filepath)
    
    def export_detailed_csv(self, filename: Optional[str] = None) -> str:
        """
        Export detailed per-symbol metrics to CSV
        
        Args:
            filename: Optional custom filename
            
        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"profile_metrics_detailed_{timestamp}.csv"
        
        filepath = self.output_dir / filename
        
        # Get detailed data from router
        detailed_data = []
        for (profile_id, symbol), perf in self.router.performance.items():
            if perf['trades'] > 0:
                win_rate = (perf['wins'] / perf['trades']) * 100
                avg_pnl = perf['total_pnl'] / perf['trades']
                
                detailed_data.append({
                    'profile_id': profile_id,
                    'symbol': symbol,
                    'trades': perf['trades'],
                    'wins': perf['wins'],
                    'win_rate': win_rate,
                    'total_pnl': perf['total_pnl'],
                    'avg_pnl': avg_pnl,
                    'last_trade_time': datetime.fromtimestamp(perf['last_trade_time']).isoformat() if perf['last_trade_time'] > 0 else 'N/A'
                })
        
        # Sort by total PnL
        detailed_data.sort(key=lambda x: x['total_pnl'], reverse=True)
        
        # Write CSV
        with open(filepath, 'w', newline='') as f:
            if detailed_data:
                writer = csv.DictWriter(f, fieldnames=detailed_data[0].keys())
                writer.writeheader()
                writer.writerows(detailed_data)
        
        print(f"✅ Exported detailed CSV: {filepath}")
        return str(filepath)
    
    def export_filtered(
        self,
        min_trades: int = 0,
        min_win_rate: float = 0.0,
        min_pnl: float = 0.0,
        symbols: Optional[List[str]] = None,
        format: str = "csv"
    ) -> str:
        """
        Export filtered profile metrics
        
        Args:
            min_trades: Minimum number of trades
            min_win_rate: Minimum win rate (0-100)
            min_pnl: Minimum total PnL
            symbols: List of symbols to include (None = all)
            format: Output format ('csv' or 'json')
            
        Returns:
            Path to exported file
        """
        # Get detailed data
        filtered_data = []
        for (profile_id, symbol), perf in self.router.performance.items():
            if perf['trades'] < min_trades:
                continue
            
            win_rate = (perf['wins'] / perf['trades']) * 100 if perf['trades'] > 0 else 0
            if win_rate < min_win_rate:
                continue
            
            if perf['total_pnl'] < min_pnl:
                continue
            
            if symbols and symbol not in symbols:
                continue
            
            filtered_data.append({
                'profile_id': profile_id,
                'symbol': symbol,
                'trades': perf['trades'],
                'wins': perf['wins'],
                'win_rate': win_rate,
                'total_pnl': perf['total_pnl'],
                'avg_pnl': perf['total_pnl'] / perf['trades'] if perf['trades'] > 0 else 0
            })
        
        # Sort by total PnL
        filtered_data.sort(key=lambda x: x['total_pnl'], reverse=True)
        
        # Export
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if format == "json":
            filename = f"profile_metrics_filtered_{timestamp}.json"
            filepath = self.output_dir / filename
            with open(filepath, 'w') as f:
                json.dump({
                    'filters': {
                        'min_trades': min_trades,
                        'min_win_rate': min_win_rate,
                        'min_pnl': min_pnl,
                        'symbols': symbols
                    },
                    'data': filtered_data
                }, f, indent=2)
        else:  # CSV
            filename = f"profile_metrics_filtered_{timestamp}.csv"
            filepath = self.output_dir / filename
            with open(filepath, 'w', newline='') as f:
                if filtered_data:
                    writer = csv.DictWriter(f, fieldnames=filtered_data[0].keys())
                    writer.writeheader()
                    writer.writerows(filtered_data)
        
        print(f"✅ Exported filtered {format.upper()}: {filepath}")
        print(f"   Filters: min_trades={min_trades}, min_win_rate={min_win_rate}%, min_pnl=${min_pnl}")
        print(f"   Results: {len(filtered_data)} profile-symbol combinations")
        return str(filepath)
    
    def export_summary_report(self, filename: Optional[str] = None) -> str:
        """
        Export a comprehensive summary report
        
        Args:
            filename: Optional custom filename
            
        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"profile_summary_report_{timestamp}.txt"
        
        filepath = self.output_dir / filename
        
        # Get metrics
        metrics = self.router.get_all_metrics()
        
        # Generate report
        with open(filepath, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("PROFILE ROUTER PERFORMANCE SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("OVERALL STATISTICS\n")
            f.write("-" * 80 + "\n")
            f.write(f"Total Trades:        {metrics.get('total_trades', 0):,}\n")
            f.write(f"Total Wins:          {metrics.get('total_wins', 0):,}\n")
            f.write(f"Overall Win Rate:    {metrics.get('overall_win_rate', 0):.2f}%\n")
            f.write(f"Total PnL:           ${metrics.get('total_pnl', 0):.2f}\n")
            f.write(f"Avg PnL per Trade:   ${metrics.get('avg_pnl_per_trade', 0):.2f}\n")
            f.write(f"Active Profiles:     {metrics.get('active_profiles', 0)}\n")
            f.write(f"Registered Profiles: {metrics.get('registered_profiles', 0)}\n")
            f.write(f"ML Enabled:          {'Yes' if metrics.get('ml_enabled', False) else 'No'}\n\n")
            
            f.write("TOP PERFORMING PROFILES\n")
            f.write("-" * 80 + "\n")
            f.write(f"{'Profile ID':<30} {'Trades':>8} {'Win%':>8} {'Avg PnL':>12} {'Total PnL':>12}\n")
            f.write("-" * 80 + "\n")
            
            for profile in metrics.get('top_profiles', []):
                f.write(f"{profile['profile_id']:<30} "
                       f"{profile['trades']:>8} "
                       f"{profile['win_rate']:>7.1f}% "
                       f"${profile['avg_pnl']:>10.2f} "
                       f"${profile['total_pnl']:>10.2f}\n")
            
            f.write("\n" + "=" * 80 + "\n")
        
        print(f"✅ Exported summary report: {filepath}")
        return str(filepath)


# CLI interface
def main():
    """Command-line interface for exporting metrics"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Export profile metrics")
    parser.add_argument('--format', choices=['csv', 'json', 'detailed', 'summary', 'all'], 
                       default='csv', help='Export format')
    parser.add_argument('--output-dir', default='exports', help='Output directory')
    parser.add_argument('--min-trades', type=int, default=0, help='Minimum trades filter')
    parser.add_argument('--min-win-rate', type=float, default=0.0, help='Minimum win rate filter')
    parser.add_argument('--min-pnl', type=float, default=0.0, help='Minimum PnL filter')
    
    args = parser.parse_args()
    
    exporter = ProfileMetricsExporter(output_dir=args.output_dir)
    
    if args.format == 'csv':
        exporter.export_all_to_csv()
    elif args.format == 'json':
        exporter.export_all_to_json()
    elif args.format == 'detailed':
        exporter.export_detailed_csv()
    elif args.format == 'summary':
        exporter.export_summary_report()
    elif args.format == 'all':
        exporter.export_all_to_csv()
        exporter.export_all_to_json()
        exporter.export_detailed_csv()
        exporter.export_summary_report()
    
    # If filters specified, also export filtered data
    if args.min_trades > 0 or args.min_win_rate > 0 or args.min_pnl > 0:
        exporter.export_filtered(
            min_trades=args.min_trades,
            min_win_rate=args.min_win_rate,
            min_pnl=args.min_pnl,
            format='csv'
        )


if __name__ == "__main__":
    main()

