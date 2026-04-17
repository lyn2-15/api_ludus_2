"""
app/services/reporte_service.py
Generación de PDF del alumno con ReportLab.
Nunca escribe el nombre real — solo alias o UUID parcial.
"""
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Estudiante, EventoAprendizaje


class ReporteService:

    async def generar_pdf(
        self, db: AsyncSession, estudiante: Estudiante, nombre_grupo: str
    ) -> bytes:
        stats = await db.execute(
            select(
                func.count(EventoAprendizaje.id_evento).label("total"),
                func.coalesce(func.avg(EventoAprendizaje.errores), 0).label("prom_errores"),
                func.coalesce(func.sum(EventoAprendizaje.monedas_ganadas), 0).label("monedas"),
                func.max(EventoAprendizaje.fecha_servidor).label("ultima"),
            ).where(EventoAprendizaje.uuid_estudiante == estudiante.uuid_estudiante)
        )
        row = stats.one()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                                rightMargin=inch, leftMargin=inch,
                                topMargin=inch, bottomMargin=inch)
        styles = getSampleStyleSheet()
        story = []

        title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=18,
                                     textColor=colors.HexColor("#1A237E"), spaceAfter=4)
        sub_style = ParagraphStyle("S", parent=styles["Normal"], fontSize=10,
                                   textColor=colors.grey, spaceAfter=16)
        info_style = ParagraphStyle("I", parent=styles["Normal"], fontSize=9)

        story.append(Paragraph("LudusAcademia+", title_style))
        story.append(Paragraph("Reporte de Progreso Académico", sub_style))

        alias = estudiante.alias_estudiante or estudiante.uuid_estudiante[:8]
        generado = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

        story.append(Paragraph(f"<b>Grupo:</b> {nombre_grupo}", info_style))
        story.append(Paragraph(f"<b>Identificador del alumno:</b> {alias}", info_style))
        story.append(Paragraph(f"<b>Fecha de generación:</b> {generado}", info_style))
        story.append(Spacer(1, 0.25 * inch))

        section_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12,
                                       textColor=colors.HexColor("#1A237E"), spaceAfter=8)
        story.append(Paragraph("Métricas de Desempeño", section_style))

        data = [
            ["Métrica", "Valor"],
            ["Misiones jugadas", str(row.total or 0)],
            ["Monedas acumuladas", f"{int(row.monedas or 0):,}"],
            ["Errores promedio", f"{float(row.prom_errores):.1f}"],
            ["Última actividad",
             row.ultima.strftime("%d/%m/%Y") if row.ultima else "Sin datos"],
        ]

        table = Table(data, colWidths=[3.5 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A237E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F5F5F5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5 * inch))

        footer_style = ParagraphStyle("F", parent=styles["Normal"], fontSize=7,
                                      textColor=colors.grey, alignment=1)
        story.append(Paragraph(
            "Documento generado por LudusAcademia+. Datos protegidos conforme a la "
            "LGPDPPSO. El identificador del alumno es seudonimizado; el nombre real "
            "vive solo en el registro escolar.",
            footer_style,
        ))

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()
