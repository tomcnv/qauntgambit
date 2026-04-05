"""
Replay diff tool for comparing decisions between runs.

Compares two replay runs or a replay against recorded decisions
to identify where the pipeline diverges.

Usage:
    diff = ReplayDiff()
    result = diff.compare(recorded_decisions, replayed_decisions)
    
    if result.has_divergences:
        for d in result.divergences:
            print(f"Divergence at {d['index']}: {d['fields']}")
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
import json


@dataclass
class DiffResult:
    """
    Result of comparing two decision sets.
    
    Attributes:
        total_compared: Total decisions compared
        matched: Number of matching decisions
        diverged: Number of divergent decisions
        divergences: List of divergence details
        extra_in_first: Decisions only in first set
        extra_in_second: Decisions only in second set
    """
    
    total_compared: int = 0
    matched: int = 0
    diverged: int = 0
    divergences: List[Dict[str, Any]] = field(default_factory=list)
    extra_in_first: int = 0
    extra_in_second: int = 0
    
    @property
    def has_divergences(self) -> bool:
        """Check if there are any divergences."""
        return self.diverged > 0 or self.extra_in_first > 0 or self.extra_in_second > 0
    
    @property
    def match_rate(self) -> float:
        """Get match rate as percentage."""
        if self.total_compared == 0:
            return 100.0
        return (self.matched / self.total_compared) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_compared": self.total_compared,
            "matched": self.matched,
            "diverged": self.diverged,
            "divergences": self.divergences,
            "extra_in_first": self.extra_in_first,
            "extra_in_second": self.extra_in_second,
            "match_rate": self.match_rate,
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            f"Compared: {self.total_compared}",
            f"Matched: {self.matched} ({self.match_rate:.1f}%)",
            f"Diverged: {self.diverged}",
        ]
        if self.extra_in_first:
            lines.append(f"Extra in first: {self.extra_in_first}")
        if self.extra_in_second:
            lines.append(f"Extra in second: {self.extra_in_second}")
        return "\n".join(lines)


class ReplayDiff:
    """
    Compare decisions between replay runs.
    
    Supports:
    - Comparing two decision lists
    - Comparing two session recordings
    - Configurable tolerance for numeric fields
    """
    
    def __init__(
        self,
        tolerance: float = 0.001,
        ignore_fields: Optional[List[str]] = None,
    ):
        """
        Initialize diff tool.
        
        Args:
            tolerance: Tolerance for numeric comparisons
            ignore_fields: Fields to ignore in comparison
        """
        self._tolerance = tolerance
        self._ignore_fields = set(ignore_fields or [])
        
        # Fields that must match exactly
        self._exact_fields = {
            "symbol",
            "blocked_reason",
            "intents_count",
            "deadband_blocked",
            "churn_guard_blocked",
            "clipped",
        }
        
        # Numeric fields with tolerance
        self._numeric_fields = {
            "p_raw",
            "p_hat",
            "s",
            "k",
            "tau",
            "vol_hat",
            "w_current",
            "w_target",
            "delta_w",
        }
    
    def compare(
        self,
        first: List[Dict[str, Any]],
        second: List[Dict[str, Any]],
    ) -> DiffResult:
        """
        Compare two lists of decisions.
        
        Args:
            first: First decision list
            second: Second decision list
            
        Returns:
            DiffResult with comparison details
        """
        result = DiffResult()
        
        min_len = min(len(first), len(second))
        result.total_compared = min_len
        
        for i in range(min_len):
            divergent_fields = self._compare_decisions(first[i], second[i])
            
            if divergent_fields:
                result.diverged += 1
                result.divergences.append({
                    "index": i,
                    "trace_id": first[i].get("trace_id"),
                    "symbol": first[i].get("symbol"),
                    "fields": divergent_fields,
                    "first": {f: first[i].get(f) for f in divergent_fields},
                    "second": {f: second[i].get(f) for f in divergent_fields},
                })
            else:
                result.matched += 1
        
        # Count extras
        result.extra_in_first = max(0, len(first) - len(second))
        result.extra_in_second = max(0, len(second) - len(first))
        
        return result
    
    def compare_sessions(
        self,
        session1_dir: str,
        session2_dir: str,
    ) -> DiffResult:
        """
        Compare decisions from two recorded sessions.
        
        Args:
            session1_dir: Path to first session
            session2_dir: Path to second session
            
        Returns:
            DiffResult with comparison details
        """
        from quantgambit.io.recorder import RecordingReader
        
        reader1 = RecordingReader(session1_dir)
        reader2 = RecordingReader(session2_dir)
        
        decisions1 = [
            r.get("decision", {})
            for r in reader1.read_stream("decision")
            if "decision" in r
        ]
        
        decisions2 = [
            r.get("decision", {})
            for r in reader2.read_stream("decision")
            if "decision" in r
        ]
        
        return self.compare(decisions1, decisions2)
    
    def _compare_decisions(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
    ) -> List[str]:
        """
        Compare two decisions.
        
        Returns list of divergent field names.
        """
        divergent = []
        
        # Check exact fields
        for field in self._exact_fields:
            if field in self._ignore_fields:
                continue
            if first.get(field) != second.get(field):
                divergent.append(field)
        
        # Check numeric fields with tolerance
        for field in self._numeric_fields:
            if field in self._ignore_fields:
                continue
            
            val1 = first.get(field)
            val2 = second.get(field)
            
            if val1 is None and val2 is None:
                continue
            if val1 is None or val2 is None:
                divergent.append(field)
                continue
            
            try:
                if abs(float(val1) - float(val2)) > self._tolerance:
                    divergent.append(field)
            except (TypeError, ValueError):
                if val1 != val2:
                    divergent.append(field)
        
        return divergent
    
    def generate_report(
        self,
        result: DiffResult,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a detailed diff report.
        
        Args:
            result: DiffResult to report on
            output_path: Optional path to write report
            
        Returns:
            Report as string
        """
        lines = [
            "=" * 60,
            "REPLAY DIFF REPORT",
            "=" * 60,
            "",
            result.summary(),
            "",
        ]
        
        if result.divergences:
            lines.append("-" * 60)
            lines.append("DIVERGENCES")
            lines.append("-" * 60)
            
            for d in result.divergences[:20]:  # Limit to first 20
                lines.append(f"\nIndex {d['index']} - {d.get('symbol', 'N/A')}")
                lines.append(f"  Trace ID: {d.get('trace_id', 'N/A')}")
                lines.append(f"  Fields: {', '.join(d['fields'])}")
                
                for field in d["fields"]:
                    first_val = d["first"].get(field)
                    second_val = d["second"].get(field)
                    lines.append(f"    {field}: {first_val} -> {second_val}")
            
            if len(result.divergences) > 20:
                lines.append(f"\n... and {len(result.divergences) - 20} more divergences")
        
        lines.append("")
        lines.append("=" * 60)
        
        report = "\n".join(lines)
        
        if output_path:
            Path(output_path).write_text(report)
        
        return report


def diff_sessions(
    session1: str,
    session2: str,
    tolerance: float = 0.001,
) -> DiffResult:
    """
    Convenience function to diff two sessions.
    
    Args:
        session1: Path to first session
        session2: Path to second session
        tolerance: Numeric tolerance
        
    Returns:
        DiffResult
    """
    diff = ReplayDiff(tolerance=tolerance)
    return diff.compare_sessions(session1, session2)
