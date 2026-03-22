"""Excel Processing Service for ERA Assistant.

This module handles:
- Parsing Excel files (bytes) to text format for AI analysis
- No external dependencies - pure Excel parsing logic
"""
import pandas as pd
import io
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class ExcelExtractionResult:
    """Result of Excel extraction."""
    filename: str = ""
    sheet_name: str = ""
    total_rows: int = 0
    total_cols: int = 0
    raw_text: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "sheet_name": self.sheet_name,
            "total_rows": self.total_rows,
            "total_cols": self.total_cols,
            "raw_text": self.raw_text,
            "error": self.error
        }

    @property
    def success(self) -> bool:
        return not self.error


@dataclass
class BatchProcessResult:
    """Result of batch processing multiple files."""
    total: int = 0
    success: int = 0
    failed: int = 0
    results: List[ExcelExtractionResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "results": [r.to_dict() for r in self.results]
        }


class ExcelProcessingService:
    """Service for parsing Excel files.

    Pure parsing logic - no external dependencies.
    Receives bytes, returns raw_text for AI analysis.
    """

    def _dataframe_to_markdown(self, df: pd.DataFrame) -> str:
        """Convert DataFrame to Markdown table format.

        This format is more AI-friendly than df.to_string():
        - Clear column headers
        - Row-by-row structure
        - No NaN clutter
        """
        lines = []

        for row_idx, (idx, row) in enumerate(df.iterrows()):
            # Each row as: | 列0内容 | 列1内容 | ... |
            row_content = " | ".join(str(cell).strip() for cell in row.values)
            lines.append(f"### 第 {row_idx + 1} 行")
            lines.append(f"| {' | '.join([f'列{i}' for i in range(len(row))])} |")
            lines.append(f"| {' | '.join(['---'] * len(row))} |")
            lines.append(f"| {row_content} |")
            lines.append("")  # Empty line between rows

        return "\n".join(lines)

    def parse_excel(
        self,
        file_content: bytes,
        filename: str = ""
    ) -> ExcelExtractionResult:
        """Parse Excel and convert to text for AI analysis.

        Args:
            file_content: Excel file content as bytes
            filename: Optional filename for reference

        Returns:
            ExcelExtractionResult with raw_text
        """
        try:
            # Read Excel without headers
            df = pd.read_excel(
                io.BytesIO(file_content),
                sheet_name=0,
                header=None
            )

            # Get sheet name
            xl = pd.ExcelFile(io.BytesIO(file_content))
            sheet_name = str(xl.sheet_names[0]) if xl.sheet_names else "Sheet1"

            # Convert to Markdown table format for better AI readability
            # Fill NaN with empty string for cleaner output
            df_clean = df.fillna('')
            raw_text = self._dataframe_to_markdown(df_clean)

            return ExcelExtractionResult(
                filename=filename,
                sheet_name=sheet_name,
                total_rows=len(df),
                total_cols=df.shape[1],
                raw_text=raw_text
            )

        except Exception as e:
            return ExcelExtractionResult(filename=filename, error=str(e))

    def parse_batch(
        self,
        items: List[Dict[str, Any]]
    ) -> BatchProcessResult:
        """Parse multiple Excel files.

        Args:
            items: List of {"file_content": bytes, "filename": str}

        Returns:
            BatchProcessResult with all results

        Example:
            items = [
                {"file_content": b"...", "filename": "report1.xlsx"},
                {"file_content": b"...", "filename": "report2.xlsx"},
            ]
            result = service.parse_batch(items)
        """
        results = [
            self.parse_excel(item["file_content"], item.get("filename", ""))
            for item in items
        ]

        success = sum(1 for r in results if r.success)
        return BatchProcessResult(
            total=len(results),
            success=success,
            failed=len(results) - success,
            results=results
        )


# Singleton
_excel_service: Optional[ExcelProcessingService] = None


def get_excel_service() -> ExcelProcessingService:
    """Get Excel processing service singleton."""
    global _excel_service
    if _excel_service is None:
        _excel_service = ExcelProcessingService()
    return _excel_service