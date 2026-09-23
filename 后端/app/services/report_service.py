"""Report business service: list + delete (《任务详细流程规范》四、十一).

Deletion releases `report_cover` and `source_photo` references via
`FileAssetService`. The system default cover is skipped automatically. Deleting
a report never rolls back or modifies the implicit-traits document.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.core.exceptions import NotFoundError
from app.db.session import session_scope
from app.models import dto
from app.models.report import Report as ReportEntity
from app.services import file_asset_service, mappers, trip_service


def list_reports(session: Session, user_id: str) -> list[dto.Report]:
    """List the user's reports, newest first."""
    reports = session.exec(
        select(ReportEntity)
        .where(ReportEntity.user_id == user_id)
        .order_by(ReportEntity.created_at.desc())
    ).all()
    return [
        mappers.report_to_dto(
            report,
            source_images=file_asset_service.list_reference_paths(
                session,
                user_id=user_id,
                owner_type="report",
                owner_id=report.id,
                role="source_photo",
            ),
        )
        for report in reports
    ]


def delete_report(user_id: str, report_id: str) -> None:
    """Delete a report and release its references (default cover skipped)."""
    with session_scope() as session:
        report = session.exec(
            select(ReportEntity).where(
                ReportEntity.id == report_id,
                ReportEntity.user_id == user_id,
            )
        ).first()
        if report is None:
            raise NotFoundError("报告不存在或已被删除")

        file_asset_service.release_and_cleanup(
            session, owner_type="report", owner_id=report_id
        )
        trip_id = report.trip_id
        session.delete(report)
        session.flush()
        trip_service.refresh_cover(session, user_id, trip_id)
