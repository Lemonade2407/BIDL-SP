import io
import re
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import StrictUndefined, nodes
from jinja2.sandbox import SandboxedEnvironment
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .common import APIError
from .config import DISCLAIMER, settings

VARIABLES = {
    "patient_no",
    "study_no",
    "study_date",
    "model_version",
    "lesion_area_ratio",
    "review_conclusion",
    "reviewer",
    "signed_at",
    "disclaimer",
    "findings",
    "impression",
    "recommendation",
}
environment = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
environment.globals.clear()
DEFAULT_TEMPLATE = """<h1>乳腺影像辅助筛查报告</h1>
<p>患者编号：{{ patient_no }}</p><p>检查编号：{{ study_no }} / {{ study_date }}</p>
<p>模型版本：{{ model_version }}；面积占比：{{ lesion_area_ratio }}</p>
<h2>影像所见</h2><p>{{ findings }}</p><h2>复核意见</h2><p>{{ impression }}</p>
<h2>建议</h2><p>{{ recommendation }}</p><p>复核结论：{{ review_conclusion }}</p>
<p>{{ disclaimer }}</p>"""


def validate_template(body, variables):
    if not re.search(r"{{\s*disclaimer\s*}}", body):
        raise APIError(422, "模板必须包含 {{ disclaimer }}")
    if any(v not in VARIABLES for v in variables):
        raise APIError(422, "模板变量不受支持")
    try:
        tree = environment.parse(body)
        for node in tree.find_all(nodes.Node):
            if type(node) not in (nodes.Output, nodes.TemplateData, nodes.Name):
                raise ValueError("only plain variable placeholders are supported")
            if isinstance(node, nodes.Name) and node.name not in VARIABLES:
                raise ValueError("unknown variable")
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup.find_all(True):
            if (
                tag.name not in ("h1", "h2", "h3", "p", "br", "strong", "b", "em", "i", "ul", "ol", "li")
                or tag.attrs
            ):
                raise ValueError("unsupported HTML or attributes")
    except Exception:
        raise APIError(422, "模板仅支持安全文本标签和简单变量占位符") from None


def render(body, values):
    try:
        html = environment.from_string(body).render(
            {**{k: "" for k in VARIABLES}, **values, "disclaimer": DISCLAIMER}
        )
        if DISCLAIMER not in BeautifulSoup(html, "html.parser").get_text():
            raise ValueError()
        return html
    except Exception:
        raise APIError(422, "报告渲染失败或缺少免责声明") from None


def pdf_bytes(report, author_name, reviewer_name):
    candidates = [
        settings.pdf_font_path,
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    available = next((path for path in candidates if path and Path(path).is_file()), None)
    font = "BIDLCJK" if available else "STSong-Light"
    if available:
        pdfmetrics.registerFont(TTFont(font, available, subfontIndex=0))
    else:
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    stream = io.BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=(210 * mm, 297 * mm),
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=24 * mm,
        bottomMargin=25 * mm,
        title="BIDL-SP 科研筛查报告",
        author="BIDL-SP",
    )
    base = ParagraphStyle("body", fontName=font, fontSize=11, leading=19, wordWrap="CJK", spaceAfter=8)
    title = ParagraphStyle(
        "title", parent=base, fontSize=19, leading=27, textColor=colors.HexColor("#163b50"), spaceAfter=16
    )
    heading = ParagraphStyle(
        "heading", parent=base, fontSize=13, leading=22, textColor=colors.HexColor("#163b50")
    )
    small = ParagraphStyle("small", parent=base, fontSize=9, leading=15)
    story = []
    soup = BeautifulSoup(report.rendered_html, "html.parser")
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        text = tag.get_text(" ", strip=True)
        style = title if tag.name == "h1" else heading if tag.name.startswith("h") else base
        story.append(Paragraph(escape(text), style))
    story.extend(
        [
            Spacer(1, 8 * mm),
            Paragraph(escape(f"报告 ID：{report.id} / 版本：{report.version}"), small),
            Paragraph(escape(f"起草：{author_name}　审核：{reviewer_name or '未签发'}"), small),
            Paragraph(
                escape(f"签发时间：{report.signed_at.isoformat() if report.signed_at else '未签发'}"), small
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#526878"))
        canvas.drawString(22 * mm, 15 * mm, DISCLAIMER)
        canvas.drawRightString(188 * mm, 15 * mm, str(doc.page))
        if report.status != "signed":
            canvas.setFillColor(colors.Color(0.75, 0.75, 0.75, alpha=0.25))
            canvas.setFont(font, 64)
            canvas.translate(105 * mm, 145 * mm)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "未签发")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
