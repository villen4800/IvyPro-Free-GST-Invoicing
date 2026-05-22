from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable, Image as RLImage, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import io, qrcode, json, os

DARK       = colors.HexColor('#1a1a2e')
ACCENT     = colors.HexColor('#e94560')
LIGHT_GRAY = colors.HexColor('#f0f0f0')
MID_GRAY   = colors.HexColor('#cccccc')
TEXT       = colors.HexColor('#333333')
GOLD       = colors.HexColor('#c17f24')
COPY_LABELS = ["ORIGINAL FOR RECIPIENT", "DUPLICATE FOR TRANSPORTER", "TRIPLICATE FOR SUPPLIER"]

from app.utils.formatters import num_to_words

# ─── QR Code for UPI / Invoice ───────────────────────────
def make_qr_image(data: str, size_mm=28):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return RLImage(buf, width=size_mm*mm, height=size_mm*mm)

def build_upi_qr(company, amount):
    """Build UPI payment QR string."""
    upi_id = getattr(company, 'upi_id', None) or ''
    if not upi_id:
        return None
    name = (company.name or '').replace(' ', '%20')
    return f"upi://pay?pa={upi_id}&pn={name}&am={amount:.2f}&cu=INR"

def build_invoice_qr(voucher, company):
    """GST e-invoice style QR data."""
    if not getattr(company, 'enable_gst', True):
        return None
    data = {
        'SellerGSTIN': company.gstin or '',
        'BuyerGSTIN': (voucher.party.gstin if voucher.party else '') or '',
        'DocNo': voucher.voucher_number,
        'DocDt': voucher.date.strftime('%d/%m/%Y'),
        'TotInvVal': str(round(voucher.total_amount, 2)),
        'ItemCnt': len(voucher.items),
        'TaxAmt': str(round(voucher.cgst_amount+voucher.sgst_amount+voucher.igst_amount, 2)),
    }
    return json.dumps(data, separators=(',',':'))
    
def build_signature_image(company, width_mm=40):
    if not company.signature_path:
        return None
    
    # Resolve absolute path to static folder
    # app/utils/invoice_pdf.py -> app/static/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, 'static', company.signature_path)
    
    if os.path.exists(path):
        try:
            from reportlab.lib.utils import ImageReader
            img_reader = ImageReader(path)
            w, h = img_reader.getSize()
            aspect = h / float(w)
            
            return RLImage(path, width=width_mm*mm, height=(width_mm * aspect)*mm)
        except Exception as e:
            print(f"Error loading signature: {e}")
            return None
    return None

def get_company_terms(company):
    """Returns a list of terms & conditions lines, dynamically replacing (CITY) or {city}."""
    if company.terms:
        lines = [line.strip() for line in company.terms.split('\n') if line.strip()]
    else:
        city_name = (company.city or "LOCAL").upper()
        lines = [
            "1. Goods once sold will not be taken back.",
            "2. Interest @18% p.a. on overdue amounts.",
            f"3. Subject to {city_name} jurisdiction only.",
            "4. E. & O.E."
        ]
    city_name = (company.city or "LOCAL").upper()
    cleaned = []
    for line in lines:
        cleaned.append(line.replace('(CITY)', city_name).replace('{city}', city_name))
    return cleaned

def get_invoice_addresses(voucher, company):
    """Extracts unified billing and shipping address snapshots for any voucher."""
    party = voucher.party
    party_name = (party.name if party else 'CASH') or 'CASH'
    
    if voucher.voucher_type in ['Purchase', 'Debit Note']:
        bill_name = party_name
        bill_addr = voucher.billing_address or ((party.address if party else '') or '')
        bill_city = voucher.billing_city or ((party.city if party else '') or '')
        bill_state = voucher.billing_state or ((party.state if party else '') or '')
        bill_pincode = voucher.billing_pincode or ((party.pincode if party else '') or '')
        bill_gstin = voucher.billing_gstin or ((party.gstin if party else '') or '')
        
        ship_name = company.name or ''
        ship_addr = company.address or ''
        ship_city = company.city or ''
        ship_state = company.state or ''
        ship_pincode = company.pincode or ''
        ship_gstin = company.gstin or ''
    else:
        bill_name = party_name
        bill_addr = voucher.billing_address or ((party.address if party else '') or '')
        bill_city = voucher.billing_city or ((party.city if party else '') or '')
        bill_state = voucher.billing_state or ((party.state if party else '') or '')
        bill_pincode = voucher.billing_pincode or ((party.pincode if party else '') or '')
        bill_gstin = voucher.billing_gstin or ((party.gstin if party else '') or '')
        
        ship_name = party_name
        ship_addr = voucher.shipping_address or bill_addr
        ship_city = voucher.shipping_city or bill_city
        ship_state = voucher.shipping_state or bill_state
        ship_pincode = voucher.shipping_pincode or bill_pincode
        ship_gstin = bill_gstin

    bill_loc = f"{bill_city}, {bill_state} {bill_pincode}".strip(', ')
    ship_loc = f"{ship_city}, {ship_state} {ship_pincode}".strip(', ')
    
    is_diff = (
        (ship_addr.strip().lower() != bill_addr.strip().lower()) or
        (ship_city.strip().lower() != bill_city.strip().lower()) or
        (ship_state.strip().lower() != bill_state.strip().lower()) or
        (ship_pincode.strip().lower() != bill_pincode.strip().lower())
    )
    
    return {
        'bill_name': bill_name, 'bill_addr': bill_addr, 'bill_city': bill_city,
        'bill_state': bill_state, 'bill_pincode': bill_pincode, 'bill_gstin': bill_gstin,
        'bill_loc': bill_loc,
        'ship_name': ship_name, 'ship_addr': ship_addr, 'ship_city': ship_city,
        'ship_state': ship_state, 'ship_pincode': ship_pincode, 'ship_gstin': ship_gstin,
        'ship_loc': ship_loc,
        'is_diff': is_diff
    }

def get_custom_texts(company):
    """Returns custom header and footer text, filtering out literal 'None' strings."""
    cht = getattr(company, 'custom_header_text', None)
    cft = getattr(company, 'custom_footer_text', None)
    if cht and str(cht).strip() == 'None': cht = None
    if cft and str(cft).strip() == 'None': cft = None
    return {'header': cht, 'footer': cft}

def get_bank_details(company):
    """Returns bank details dictionary."""
    return {
        'bank_name': company.bank_name or '',
        'bank_account': company.bank_account or '',
        'bank_ifsc': company.bank_ifsc or '',
        'upi_id': company.upi_id or '',
        'bank_branch': company.bank_branch or '',
        'has_bank': bool(company.bank_account or company.upi_id)
    }

# ─── Receipt PDF Generator (Indian Format) ────────────────
def generate_receipt_pdf(voucher, company, pagesize=None):
    if pagesize is None:
        layout = getattr(company, 'print_layout', 'A4') or 'A4'
        if layout == 'A5':
            pagesize = A5
        elif layout == 'Thermal':
            w_mm = getattr(company, 'thermal_width', 80.0) or 80.0
            h_mm = 145.0
            if getattr(company, 'terms', None) or get_company_terms(company):
                h_mm += 25.0
            sig_img = build_signature_image(company, width_mm=26.0)
            if sig_img or getattr(company, 'signature_path', None):
                h_mm += 30.0
            if voucher.narration:
                h_mm += 15.0
            pagesize = (w_mm * mm, h_mm * mm)
        elif layout == 'Custom':
            w_mm = getattr(company, 'custom_width', 210.0) or 210.0
            h_mm = getattr(company, 'custom_height', 297.0) or 297.0
            pagesize = (w_mm * mm, h_mm * mm)
        else:
            pagesize = A4

    buffer = io.BytesIO()
    is_thermal = pagesize[0] < 100*mm
    left_m = 4.0 if is_thermal else 12.0
    right_m = 4.0 if is_thermal else 12.0
    top_m = 5.0 if is_thermal else 15.0
    bot_m = 5.0 if is_thermal else 15.0

    doc = SimpleDocTemplate(buffer, pagesize=pagesize,
                            title=f"{voucher.voucher_type} {voucher.voucher_number}",
                            leftMargin=left_m*mm, rightMargin=right_m*mm,
                            topMargin=top_m*mm, bottomMargin=bot_m*mm)
    story = []
    W = pagesize[0] - (left_m + right_m)*mm

    # Styles
    scale = 1.0
    if is_thermal:
        base_fs = getattr(company, 'thermal_font_size', 7.5) or 7.5
        scale = base_fs / 9.5

    h_co = ParagraphStyle('h_co', fontSize=24*scale, textColor=DARK, fontName='Helvetica-Bold', alignment=TA_CENTER, leading=30*scale)
    h_sub = ParagraphStyle('h_sub', fontSize=10*scale, textColor=TEXT, fontName='Helvetica', alignment=TA_CENTER, leading=14*scale)
    h_title = ParagraphStyle('h_title', fontSize=18*scale, textColor=ACCENT, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=20*scale if not is_thermal else 8*scale, spaceBefore=10*scale if not is_thermal else 4*scale)
    norm = ParagraphStyle('norm', fontSize=11*scale, textColor=TEXT, fontName='Helvetica', leading=18*scale)
    label = ParagraphStyle('label', fontSize=11*scale, textColor=TEXT, fontName='Helvetica-Bold', leading=18*scale)
    box_style = ParagraphStyle('box', fontSize=14*scale, fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=DARK)

    # 1. Company Header (Using Table to avoid overlap)
    vtype = voucher.voucher_type
    title = vtype.upper()
    party_label = "Received with thanks from:" if vtype == 'Receipt' else "Paid to / Credited to:"
    ref_label = "Received For / Towards:" if vtype == 'Receipt' else "Payment For / Towards:"

    co_info = []
    if company.address: co_info.append(company.address)
    if company.city: co_info.append(company.city)
    if company.phone: co_info.append(f"Tel: {company.phone}")
    if company.gstin: co_info.append(f"GSTIN: {company.gstin}")
    
    if is_thermal:
        header_data = [[Paragraph(f"<b>{company.name}</b>", h_co)]]
        for info in co_info:
            header_data.append([Paragraph(info, h_sub)])
    else:
        header_data = [
            [Paragraph(f"<b>{company.name}</b>", h_co)],
            [Paragraph(" | ".join(co_info), h_sub)]
        ]
        
    hdr_tbl = Table(header_data, colWidths=[W])
    hdr_tbl.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-0), 0),
        ('BOTTOMPADDING', (0,0), (-1,-0), 5),
        ('TOPPADDING', (0,1), (-1,1), 5),
        ('BOTTOMPADDING', (0,1), (-1,-1), 0)
    ]))
    story.append(hdr_tbl)
    
    story.append(HRFlowable(width='100%', thickness=0.8 if is_thermal else 1.5, color=ACCENT, spaceAfter=8 if is_thermal else 10))
    story.append(Paragraph(title, h_title))
 
    # 2. Receipt No & Date
    info_table = Table([
        [Paragraph(f"<b>Voucher No:</b> {voucher.voucher_number}", norm),
         Paragraph(f"<b>Date:</b> {voucher.date.strftime('%d/%m/%Y')}", ParagraphStyle('r', fontSize=11*scale, alignment=TA_RIGHT))]
    ], colWidths=[0.5*W, 0.5*W])
    info_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(info_table)
    story.append(Spacer(1, 4*mm if is_thermal else 10*mm))
 
    # 3. Main Content
    party_name = "_________________________________"
    if voucher.party and voucher.party.name not in ['Cash', 'Bank Account', 'Bank']:
        party_name = voucher.party.name
    elif voucher.ledger_entries:
        for entry in voucher.ledger_entries:
            val = entry.credit if vtype == 'Receipt' else entry.debit
            if val > 0 and entry.ledger and entry.ledger.name not in ['Cash', 'Bank Account', 'Bank']:
                party_name = entry.ledger.name
                break
    
    amt_words = num_to_words(voucher.total_amount)
    
    bank_info = []
    p_mode = voucher.payment_mode or "Cash"
    if voucher.payment_ledger:
        if voucher.payment_ledger.group and voucher.payment_ledger.group.name == 'Bank Accounts':
            p_mode = 'Bank'
            bank_info.append(voucher.payment_ledger.name)
        else:
            p_mode = 'Cash'
    elif p_mode != 'Cash':
        bank_info.append(p_mode)
    
    for e in voucher.ledger_entries:
        if e.inst_no:
            info = f"#{e.inst_no}"
            if e.inst_date: info += f" dt {e.inst_date.strftime('%d-%m-%Y')}"
            if e.bank_name: info += f" ({e.bank_name})"
            bank_info.append(info)
            break
            
    payment_display = " / ".join(bank_info) if bank_info else p_mode
    received_for = voucher.narration or (f"Against Ref: {voucher.ref_number}" if voucher.ref_number else "_________________________________")
 
    body_data = [
        [Paragraph(party_label, label), Paragraph(party_name, norm)],
        [Paragraph("The sum of Rupees:", label), Paragraph(amt_words, norm)],
        [Paragraph("By:", label), Paragraph(payment_display, norm)],
        [Paragraph(ref_label, label), Paragraph(received_for, norm)],
    ]
    
    if is_thermal:
        body_data_t = []
        for row in body_data:
            body_data_t.append([row[0]])
            body_data_t.append([row[1]])
        body_tbl = Table(body_data_t, colWidths=[W])
        body_tbl.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
    else:
        body_tbl = Table(body_data, colWidths=[0.3*W, 0.7*W])
        body_tbl.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ]))
    story.append(body_tbl)
    story.append(Spacer(1, 5*mm if is_thermal else 15*mm))
 
    # 4. Amount Box & Signature
    sig_block = [
        Paragraph(f"For <b>{company.name}</b>", ParagraphStyle('s1', fontSize=11, alignment=TA_RIGHT)),
    ]
    sig_img = build_signature_image(company, width_mm=30)
    if sig_img:
        sig_block.append(Spacer(1, 2*mm))
        sig_block.append(sig_img)
        sig_block.append(Spacer(1, 2*mm))
    else:
        sig_block.append(Spacer(1, 15*mm))
        
    sig_block.append(Paragraph("Authorised Signatory", ParagraphStyle('s2', fontSize=11, alignment=TA_RIGHT, fontName='Helvetica-Bold')))
 
    if is_thermal:
        amt_box = Table([[Paragraph(f"Rs. {voucher.total_amount:,.2f}", box_style)]], 
                        colWidths=[W],
                        style=[
                            ('BOX', (0,0), (-1,-1), 1.5, DARK),
                            ('BACKGROUND', (0,0), (-1,-1), LIGHT_GRAY),
                            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                            ('TOPPADDING', (0,0), (-1,-1), 6),
                            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                        ])
        amt_box.hAlign = 'CENTER'
        story.append(amt_box)
        story.append(Spacer(1, 4*mm))
        
        sig_tbl = Table([[Paragraph(f"For <b>{company.name}</b>", ParagraphStyle('s1_c', fontSize=10*scale, alignment=TA_CENTER))],
                         [sig_img if sig_img else Spacer(1, 8*mm)],
                         [Paragraph("Authorised Signatory", ParagraphStyle('s2_c', fontSize=10*scale, alignment=TA_CENTER, fontName='Helvetica-Bold'))]],
                        colWidths=[W])
        sig_tbl.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        story.append(sig_tbl)
    else:
        amt_box = Table([[Paragraph(f"Rs. {voucher.total_amount:,.2f}", box_style)]], 
                        colWidths=[0.4*W],
                        style=[
                            ('BOX', (0,0), (-1,-1), 2, DARK),
                            ('BACKGROUND', (0,0), (-1,-1), LIGHT_GRAY),
                            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                            ('TOPPADDING', (0,0), (-1,-1), 10),
                            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                        ])
        bottom_table = Table([
            [amt_box, sig_block]
        ], colWidths=[0.4*W, 0.6*W])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ]))
        story.append(Spacer(1, 15*mm))
        story.append(bottom_table)
    
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def draw_watermark(canvas, doc):
    if hasattr(doc, 'watermark_path') and doc.watermark_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        wp = os.path.join(base_dir, 'static', doc.watermark_path)
        if os.path.exists(wp):
            canvas.saveState()
            try:
                w, h = doc.pagesize
                canvas.drawImage(wp, (w - 80*mm)/2, (h - 80*mm)/2, width=80*mm, height=80*mm, mask='auto')
            except Exception as e:
                print(f"Watermark error: {e}")
            canvas.restoreState()

def generate_modern_invoice_pdf(voucher, company, pagesize=None):
    if pagesize is None:
        layout = getattr(company, 'print_layout', 'A4') or 'A4'
        if layout == 'A5':
            pagesize = A5
        elif layout == 'Thermal':
            w_mm = getattr(company, 'thermal_width', 80.0) or 80.0
            num_items = len(voucher.items)
            h_mm = 175.0 + (num_items * 22.0)
            
            # Check addresses diff
            addrs = get_invoice_addresses(voucher, company)
            if addrs['is_diff']:
                h_mm += 40.0
                
            # Check bank details
            bank = get_bank_details(company)
            if bank['has_bank']:
                h_mm += 35.0
                
            # Check QR
            qr_placement = getattr(company, 'qr_placement', 'BOTTOM_CENTER') or 'BOTTOM_CENTER'
            if qr_placement != 'TOP_RIGHT' and getattr(company, 'show_upi_qr', True) and company.upi_id:
                h_mm += 30.0
                
            # Check GST breakdown
            is_composition = getattr(company, 'gst_registration_type', 'Regular') == 'Composition'
            hide_gst_on_invoice = is_composition and voucher.voucher_type == 'Sales'
            if getattr(company, 'show_gst_summary', True) and voucher.voucher_type in ['Sales', 'Purchase'] and not hide_gst_on_invoice:
                h_mm += 30.0
                
            # Check terms
            if getattr(company, 'terms', None) or get_company_terms(company):
                h_mm += 25.0
                
            # Check signature
            sig_img = build_signature_image(company, width_mm=26.0)
            if sig_img or getattr(company, 'signature_path', None):
                h_mm += 35.0
                
            if voucher.narration:
                h_mm += 15.0
                
            pagesize = (w_mm * mm, h_mm * mm)
        elif layout == 'Custom':
            w_mm = getattr(company, 'custom_width', 210.0) or 210.0
            h_mm = getattr(company, 'custom_height', 297.0) or 297.0
            pagesize = (w_mm * mm, h_mm * mm)
        else:
            pagesize = A4

    is_thermal = pagesize[0] < 100*mm

    buffer = io.BytesIO()
    top_m = getattr(company, 'margin_top', 10.0) or 10.0
    bot_m = getattr(company, 'margin_bottom', 10.0) or 10.0
    left_m = getattr(company, 'margin_left', 10.0) or 10.0
    right_m = getattr(company, 'margin_right', 10.0) or 10.0

    if is_thermal:
        if left_m >= 8.0: left_m = 4.0
        if right_m >= 8.0: right_m = 4.0
        if top_m >= 8.0: top_m = 4.0
        if bot_m >= 8.0: bot_m = 4.0

    doc = SimpleDocTemplate(buffer, pagesize=pagesize,
                            title=f"{voucher.voucher_type} {voucher.voucher_number}",
                            leftMargin=left_m*mm, rightMargin=right_m*mm,
                            topMargin=top_m*mm, bottomMargin=bot_m*mm)
    story = []
    W = pagesize[0] - (left_m + right_m)*mm # Total Usable Width

    num_copies = getattr(company, 'invoice_copies', 1) or 1
    try:
        num_copies = max(1, min(3, int(num_copies)))
    except (ValueError, TypeError):
        num_copies = 1

    H = pagesize[1]
    is_small = pagesize[0] < 160*mm and not is_thermal
    
    if is_thermal:
        base_fs = getattr(company, 'thermal_font_size', 7.5) or 7.5
    elif is_small:
        base_fs = getattr(company, 'a5_font_size', 8.0) or 8.0
    else:
        base_fs = getattr(company, 'a4_font_size', 9.5) or 9.5
        
    scale = base_fs / 9.5

    paper_type = getattr(company, 'paper_type', 'Plain') or 'Plain'
    is_preprinted = (paper_type == 'Pre-printed')
    is_letterhead = (paper_type == 'Letterhead')

    th_bg_hex = getattr(company, 'table_header_bg', '#1a1a2e') or '#1a1a2e'
    th_fg_hex = getattr(company, 'table_header_text_color', '#ffffff') or '#ffffff'
    primary_hex = getattr(company, 'primary_color', '#e94560') or '#e94560'

    if is_preprinted:
        th_bg = None
        th_fg = colors.black
        primary_c = colors.white
    else:
        th_bg = colors.HexColor(th_bg_hex)
        th_fg = colors.HexColor(th_fg_hex)
        primary_c = colors.HexColor(primary_hex)


    h_align_str = getattr(company, 'header_alignment', 'LEFT') or 'LEFT'
    h_align = TA_CENTER if h_align_str == 'CENTER' else (TA_RIGHT if h_align_str == 'RIGHT' else TA_LEFT)

    # ── Modern Styles with Scaling ──────────────────────
    h_co = ParagraphStyle('h_co', fontSize=18*scale, fontName='Helvetica-Bold', textColor=colors.black, leading=21*scale, alignment=h_align)
    h_gst = ParagraphStyle('h_gst', fontSize=9*scale, fontName='Helvetica-Bold', textColor=colors.black, leading=11*scale, alignment=h_align)
    h_vtype = ParagraphStyle('h_vtype', fontSize=22*scale, fontName='Helvetica-Bold', textColor=colors.black, alignment=TA_RIGHT, leading=25*scale)
    h_vnum = ParagraphStyle('h_vnum', fontSize=13*scale, fontName='Helvetica-Bold', textColor=colors.black, alignment=TA_RIGHT, leading=15*scale)
    h_vdate = ParagraphStyle('h_vdate', fontSize=9*scale, fontName='Helvetica', textColor=colors.grey, alignment=TA_RIGHT, leading=11*scale)
    
    label_s = ParagraphStyle('label_s', fontSize=8*scale, fontName='Helvetica', textColor=colors.grey, textTransform='uppercase', leading=10*scale)
    val_s = ParagraphStyle('val_s', fontSize=11*scale, fontName='Helvetica-Bold', textColor=colors.black, leading=13*scale, spaceBefore=2)
    addr_s = ParagraphStyle('addr_s', fontSize=9*scale, fontName='Helvetica', textColor=colors.grey, leading=11*scale)
    
    th_s = ParagraphStyle('th_s', fontSize=9*scale, fontName='Helvetica-Bold', textColor=th_fg, textTransform='uppercase', alignment=TA_LEFT)
    th_r = ParagraphStyle('th_r', fontSize=9*scale, fontName='Helvetica-Bold', textColor=th_fg, textTransform='uppercase', alignment=TA_RIGHT)
    if is_thermal:
        th_s.textColor = colors.black
        th_r.textColor = colors.black
    tr_s = ParagraphStyle('tr_s', fontSize=9.5*scale, fontName='Helvetica', textColor=colors.black, leading=14*scale)
    tr_b = ParagraphStyle('tr_b', fontSize=9.5*scale, fontName='Helvetica-Bold', textColor=colors.black, leading=14*scale)
    tr_r = ParagraphStyle('tr_r', fontSize=9.5*scale, fontName='Helvetica', textColor=colors.black, leading=14*scale, alignment=TA_RIGHT)
    tr_rb = ParagraphStyle('tr_rb', fontSize=9.5*scale, fontName='Helvetica-Bold', textColor=colors.black, leading=14*scale, alignment=TA_RIGHT)
    
    is_composition = getattr(company, 'gst_registration_type', 'Regular') == 'Composition'
    hide_gst_on_invoice = is_composition and voucher.voucher_type == 'Sales'

    qr_placement = getattr(company, 'qr_placement', 'BOTTOM_CENTER') or 'BOTTOM_CENTER'

    for copy_idx in range(num_copies):
        # Copy Label
        story.append(Paragraph(COPY_LABELS[copy_idx], ParagraphStyle('cp', fontSize=6*scale, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=1)))

        # Logo Handling
        logo_obj = None
        if (not is_letterhead) and (not is_preprinted) and company.logo_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            lp = os.path.join(base_dir, 'static', company.logo_path)
            if os.path.exists(lp):
                logo_obj = RLImage(lp, width=15*mm, height=15*mm, kind='proportional')

        if is_letterhead or is_preprinted:
            # Leave space for pre-printed letterhead info
            header_left_block = [Spacer(1, 35*mm)]
        else:
            co_name_text = company.name.upper() if company.name else 'COMPANY'
            co_details = [Paragraph(co_name_text, h_co)]
            
            ctexts = get_custom_texts(company)
            if ctexts['header']:
                co_details.append(Paragraph(f"<i>{ctexts['header']}</i>", ParagraphStyle('cht', fontSize=8.5*scale, fontName='Helvetica-Oblique', textColor=primary_c, leading=10*scale, alignment=h_align)))

            if getattr(company, 'enable_gst', True):
                co_details.append(Paragraph(f"GSTIN: {company.gstin or ''}", h_gst))
                if is_composition and voucher.voucher_type == 'Sales':
                    co_details.append(Paragraph("<b>COMPOSITION TAXABLE PERSON</b>", h_gst))
                    co_details.append(Paragraph("<font size='7'>(Not eligible to collect tax on supplies)</font>", h_gst))
            
            # Contact info in smaller font
            contact_style = ParagraphStyle('contact', fontSize=6.5*scale, textColor=colors.grey, leading=7.5*scale, alignment=h_align)
            addr_parts = []
            if company.address: addr_parts.append(company.address)
            if company.city: addr_parts.append(company.city)
            if company.state: addr_parts.append(f"{company.state} {company.pincode or ''}")
            
            if addr_parts:
                co_details.append(Paragraph(", ".join(addr_parts), contact_style))
            
            contact_parts = []
            if company.phone: contact_parts.append(f"Phone: {company.phone}")
            if company.email: contact_parts.append(f"Email: {company.email}")
            
            if contact_parts:
                co_details.append(Paragraph(" | ".join(contact_parts), contact_style))

            logo_placement = getattr(company, 'logo_placement', 'LEFT') or 'LEFT'
            if logo_placement == 'TOP_CENTER' and logo_obj:
                logo_obj.hAlign = 'CENTER'
                co_details.insert(0, logo_obj)
                co_details.insert(1, Spacer(1, 2*mm))
                header_left_block = co_details
            elif logo_placement == 'RIGHT' and logo_obj:
                logo_obj.hAlign = 'RIGHT'
                header_left_block = Table([[co_details, logo_obj]], colWidths=[0.45*W, 0.15*W])
                header_left_block.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
            elif logo_obj:
                logo_obj.hAlign = 'LEFT'
                header_left_block = Table([[logo_obj, co_details]], colWidths=[0.15*W, 0.45*W])
                header_left_block.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
            else:
                header_left_block = co_details

        vtype_text = "TAX INVOICE" if voucher.voucher_type == 'Sales' else voucher.voucher_type.upper()
        top_right_block = [
            Paragraph(vtype_text, h_vtype),
            Paragraph(f"#{voucher.voucher_number}", h_vnum),
            Paragraph(f"Date: {voucher.date.strftime('%d %b %Y')}", h_vdate)
        ]
        
        if qr_placement == 'TOP_RIGHT':
            qr_top = []
            if getattr(company, 'show_upi_qr', True) and company.upi_id:
                qr_top.append(make_qr_image(build_upi_qr(company, voucher.total_amount), 16*scale))
            elif getattr(company, 'show_invoice_qr', False) and getattr(company, 'enable_gst', True):
                qr_top.append(make_qr_image(build_invoice_qr(voucher, company), 16*scale))
            
            if qr_top:
                tr_table = Table([[top_right_block, qr_top]], colWidths=[0.25*W, 0.15*W])
                tr_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
                top_right_cell = tr_table
            else:
                top_right_cell = top_right_block
        else:
            top_right_cell = top_right_block

        if is_thermal:
            thermal_hdr = []
            if not (is_letterhead or is_preprinted):
                if logo_obj:
                    logo_obj.hAlign = 'CENTER'
                    thermal_hdr.append(logo_obj)
                    thermal_hdr.append(Spacer(1, 2*mm))
                # Add company details
                for f in co_details:
                    thermal_hdr.append(f)
            else:
                thermal_hdr.append(Spacer(1, 10*mm))
            
            # Dashed line
            thermal_hdr.append(Spacer(1, 2*mm))
            thermal_hdr.append(HRFlowable(width=W, thickness=0.8, color=primary_c, spaceBefore=1, spaceAfter=4, hAlign='CENTER'))
            
            # TAX INVOICE (centered)
            h_vtype_thermal = ParagraphStyle('h_vtype_t', parent=h_vtype, alignment=TA_CENTER, fontSize=11*scale, leading=13*scale)
            vtype_text = "TAX INVOICE" if voucher.voucher_type == 'Sales' else voucher.voucher_type.upper()
            thermal_hdr.append(Paragraph(vtype_text, h_vtype_thermal))
            
            # Number & Date
            h_vnum_t = ParagraphStyle('h_vnum_t', parent=h_vnum, fontSize=8.5*scale, leading=10*scale, alignment=TA_LEFT)
            h_vdate_t = ParagraphStyle('h_vdate_t', parent=h_vdate, fontSize=8.5*scale, leading=10*scale, alignment=TA_RIGHT)
            
            num_date_tbl = Table([
                [Paragraph(f"Invoice: #{voucher.voucher_number}", h_vnum_t),
                 Paragraph(f"Date: {voucher.date.strftime('%d %b %Y')}", h_vdate_t)]
            ], colWidths=[0.5*W, 0.5*W])
            num_date_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ]))
            thermal_hdr.append(Spacer(1, 1.5*mm))
            thermal_hdr.append(num_date_tbl)
            
            # Another divider
            thermal_hdr.append(Spacer(1, 1.5*mm))
            thermal_hdr.append(HRFlowable(width=W, thickness=0.8, color=primary_c, spaceBefore=1, spaceAfter=4, hAlign='CENTER'))
            
            hdr_flowables = thermal_hdr
            hr_flowables = []
        else:
            header_data = [[header_left_block, top_right_cell]]
            hdr_tbl = Table(header_data, colWidths=[0.6*W, 0.4*W])
            hdr_tbl.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
            hdr_flowables = [hdr_tbl, Spacer(1, 4*mm)]
            
            hr_flow = HRFlowable(width=W, thickness=0 if is_preprinted else 1.0, color=primary_c, spaceBefore=2, spaceAfter=12, hAlign='CENTER')
            hr_flowables = [hr_flow]
        
        # 2. Bill To & Payment Info
        addrs = get_invoice_addresses(voucher, company)
        label_text = "BILL FROM / SUPPLIER" if voucher.voucher_type in ['Purchase', 'Debit Note'] else "BILL TO"
        
        bill_addr_parts = []
        if addrs['bill_addr']: bill_addr_parts.append(addrs['bill_addr'])
        if addrs['bill_loc']: bill_addr_parts.append(addrs['bill_loc'])

        if is_thermal:
            bill_to = [
                Paragraph(f"<b>PARTY:</b> {addrs['bill_name']}", ParagraphStyle('p_name', parent=val_s, fontSize=8.5*scale, spaceBefore=0)),
            ]
            if bill_addr_parts:
                bill_to.append(Paragraph("<br/>".join(bill_addr_parts), addr_s))
            if addrs['bill_gstin'] and getattr(company, 'enable_gst', True):
                bill_to.append(Paragraph(f"GSTIN: {addrs['bill_gstin']}", addr_s))

            ship_to = []
            if addrs['is_diff']:
                ship_to = [
                    Spacer(1, 2*mm),
                    Paragraph("<b>SHIP TO:</b>", label_s),
                    Paragraph(addrs['ship_name'], val_s),
                ]
                ship_addr_parts = []
                if addrs['ship_addr']: ship_addr_parts.append(addrs['ship_addr'])
                if addrs['ship_loc']: ship_addr_parts.append(addrs['ship_loc'])
                if ship_addr_parts:
                    ship_to.append(Paragraph("<br/>".join(ship_addr_parts), addr_s))
                if addrs['ship_gstin'] and getattr(company, 'enable_gst', True):
                    ship_to.append(Paragraph(f"GSTIN: {addrs['ship_gstin']}", addr_s))
        else:
            bill_to = [
                Paragraph(label_text, label_s),
                Paragraph(addrs['bill_name'], val_s),
                Paragraph("<br/>".join(bill_addr_parts) if bill_addr_parts else "", addr_s),
                Paragraph(f"GSTIN: {addrs['bill_gstin']}" if addrs['bill_gstin'] and getattr(company, 'enable_gst', True) else "", addr_s)
            ]

            # Ship To
            ship_addr_parts = []
            if addrs['ship_addr']: ship_addr_parts.append(addrs['ship_addr'])
            if addrs['ship_loc']: ship_addr_parts.append(addrs['ship_loc'])

            ship_to = [
                Paragraph("SHIP TO / CONSIGNEE", label_s),
                Paragraph(addrs['ship_name'], val_s),
                Paragraph("<br/>".join(ship_addr_parts) if ship_addr_parts else "", addr_s),
                Paragraph(f"GSTIN: {addrs['ship_gstin']}" if addrs['ship_gstin'] and getattr(company, 'enable_gst', True) else "", addr_s)
            ]
        
        pay_mode_str = voucher.payment_mode or 'Credit'
        if pay_mode_str.lower() == 'credit' and party and party.credit_days:
            pay_mode_str = f"Credit ({party.credit_days} Days)"
            
        pay_info = [
            Paragraph("PAYMENT DETAILS", ParagraphStyle('pay_lbl', parent=label_s, alignment=TA_RIGHT)),
            Paragraph(f"Mode: <b>{pay_mode_str}</b>", ParagraphStyle('p1', fontSize=8.5*scale, alignment=TA_RIGHT)),
        ]
        if voucher.payment_ledger and pay_mode_str.lower() != 'credit':
            pay_info.append(Paragraph(f"A/c: {voucher.payment_ledger.name}", ParagraphStyle('p3', fontSize=7.5*scale, alignment=TA_RIGHT, textColor=colors.grey)))
            
        if voucher.ref_number:
            pay_info.append(Paragraph(f"Ref: {voucher.ref_number}", ParagraphStyle('p2', fontSize=7.5*scale, alignment=TA_RIGHT, textColor=colors.grey)))
        
        if voucher.eway_bill_no and getattr(company, 'enable_gst', True):
            pay_info.append(Spacer(1, 1*mm))
            pay_info.append(Paragraph("E-WAY BILL", ParagraphStyle('ew_lbl', parent=label_s, alignment=TA_RIGHT, textColor=colors.black)))
            pay_info.append(Paragraph(f"No: <b>{voucher.eway_bill_no}</b>", ParagraphStyle('ew_v', fontSize=7*scale, alignment=TA_RIGHT)))
        
        if voucher.reverse_charge:
            pay_info.append(Spacer(1, 1*mm))
            pay_info.append(Paragraph("REVERSE CHARGE", ParagraphStyle('rc_lbl', parent=label_s, alignment=TA_RIGHT, textColor=colors.black)))
            pay_info.append(Paragraph("<b>YES (Sec 9(4))</b>", ParagraphStyle('rc_v', fontSize=7*scale, alignment=TA_RIGHT)))

        if is_thermal:
            for p in pay_info:
                if hasattr(p, 'style'):
                    p.style.alignment = TA_LEFT
            info_data = [[bill_to]]
            if addrs['is_diff']: info_data.append([ship_to])
            info_data.append([pay_info])
            info_tbl = Table(info_data, colWidths=[1.0*W])
        else:
            info_tbl = Table([[bill_to, ship_to, pay_info]], colWidths=[0.35*W, 0.35*W, 0.3*W])
            
        info_tbl.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        
        # 3. Items Table
        show_gst_cols = getattr(company, 'enable_gst', True) and not hide_gst_on_invoice
        
        if is_thermal:
            hdrs = [
                Paragraph("DESCRIPTION", th_s), 
                Paragraph("QTY", th_r), 
                Paragraph("TOTAL", th_r)
            ]
            i_widths = [0.50*W, 0.18*W, 0.32*W]
        elif show_gst_cols:
            hdrs = [
                Paragraph("#", th_s), 
                Paragraph("DESCRIPTION", th_s), 
                Paragraph("HSN", th_s),
                Paragraph("QTY", th_r), 
                Paragraph("RATE", th_r), 
                Paragraph("GST %", th_r),
                Paragraph("GST AMT", th_r),
                Paragraph("TOTAL", th_r)
            ]
            i_widths = [0.05*W, 0.28*W, 0.08*W, 0.10*W, 0.13*W, 0.10*W, 0.12*W, 0.14*W]
        else:
            hdrs = [
                Paragraph("#", th_s), 
                Paragraph("DESCRIPTION", th_s), 
                Paragraph("QTY", th_r), 
                Paragraph("RATE", th_r), 
                Paragraph("TOTAL", th_r)
            ]
            i_widths = [0.05*W, 0.50*W, 0.12*W, 0.15*W, 0.18*W]
            
        data = [hdrs]
        for idx, item in enumerate(voucher.items, 1):
            desc_text = (item.description or (item.stock_item.name if item.stock_item else '—')).upper()
            if item.serial_numbers:
                sn_list = [sn.serial_number for sn in item.serial_numbers]
                desc_text += f"<br/><font size='7.5' color='#444444'><b>S/N: {', '.join(sn_list)}</b></font>"
            desc = Paragraph(desc_text, tr_b)
            
            if is_thermal:
                unit_symbol = (item.unit or (item.stock_item.unit.symbol if item.stock_item and item.stock_item.unit else 'NOS')).upper()
                data.append([
                    desc,
                    Paragraph(f"{item.qty:g}<br/><font size='6.5' color='#666666'>{unit_symbol}</font>", tr_r),
                    Paragraph(f"<b>{item.total_amount:,.2f}</b>", tr_rb)
                ])
            elif show_gst_cols:
                gst_amt = (item.cgst_amount or 0) + (item.sgst_amount or 0) + (item.igst_amount or 0)
                data.append([
                    Paragraph(str(idx), tr_s),
                    desc,
                    Paragraph(item.hsn_code or '', tr_s),
                    Paragraph(f"{item.qty:g} {(item.unit or (item.stock_item.unit.symbol if item.stock_item and item.stock_item.unit else 'NOS')).upper()}", tr_r),
                    Paragraph(f"{item.rate:,.2f}", tr_r),
                    Paragraph(f"{item.gst_rate or 0:g}%", tr_r),
                    Paragraph(f"{gst_amt:,.2f}", tr_r),
                    Paragraph(f"<b>{item.total_amount:,.2f}</b>", tr_rb)
                ])
            else:
                data.append([
                    Paragraph(str(idx), tr_s),
                    desc,
                    Paragraph(f"{item.qty:g} {(item.unit or (item.stock_item.unit.symbol if item.stock_item and item.stock_item.unit else 'NOS')).upper()}", tr_r),
                    Paragraph(f"{item.rate:,.2f}", tr_r),
                    Paragraph(f"<b>{item.total_amount:,.2f}</b>", tr_rb)
                ])
        
        item_tbl = Table(data, colWidths=i_widths)
        if is_thermal:
            item_tbl.setStyle(TableStyle([
                ('LINEABOVE', (0,0), (-1,0), 0.5, primary_c),
                ('LINEBELOW', (0,0), (-1,0), 0.5, primary_c),
                ('LINEBELOW', (0,-1), (-1,-1), 0.5, primary_c),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ]))
        else:
            item_tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), None if is_preprinted else th_bg),
                ('LINEBELOW', (0,0), (-1,0), 0 if is_preprinted else 1.0, primary_c),
                ('LINEBELOW', (0,1), (-1,-2), 0 if is_preprinted else 0.4, colors.lightgrey),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('ALIGN', (0,0), (0,-1), 'LEFT'),
            ]))
        
        # 4. Totals
        total_data = []
        if is_thermal:
            total_data.append([Paragraph("Subtotal", tr_r), Paragraph(f"<b>Rs.{voucher.taxable_amount:,.2f}</b>", tr_rb)])
            if show_gst_cols:
                gst_amt = voucher.cgst_amount + voucher.sgst_amount + voucher.igst_amount
                if gst_amt > 0:
                    total_data.append([Paragraph("GST Total", tr_r), Paragraph(f"<b>Rs.{gst_amt:,.2f}</b>", tr_rb)])
            total_data.append([Paragraph("NET TOTAL", ParagraphStyle('gt', fontSize=10*scale, fontName='Helvetica-Bold')), 
                               Paragraph(f"<b>Rs.{voucher.total_amount:,.2f}</b>", ParagraphStyle('gt_v', fontSize=10*scale, fontName='Helvetica-Bold', alignment=TA_RIGHT))])
            tot_tbl = Table(total_data, colWidths=[0.6*W, 0.4*W])
            tot_tbl.setStyle(TableStyle([
                ('LINEABOVE', (0,-1), (-1,-1), 0.5, primary_c),
                ('LINEBELOW', (0,-1), (-1,-1), 0.5, primary_c),
                ('TOPPADDING', (0,-1), (-1,-1), 4),
                ('BOTTOMPADDING', (0,-1), (-1,-1), 4),
            ]))
        else:
            if show_gst_cols:
                total_data.append([None, Paragraph("Taxable Value", tr_r), Paragraph(f"<b>Rs.{voucher.taxable_amount:,.2f}</b>", tr_rb)])
                if voucher.is_igst:
                    total_data.append([None, Paragraph("IGST Total", tr_r), Paragraph(f"<b>Rs.{voucher.igst_amount:,.2f}</b>", tr_rb)])
                else:
                    total_data.append([None, Paragraph("CGST Total", tr_r), Paragraph(f"<b>Rs.{voucher.cgst_amount:,.2f}</b>", tr_rb)])
                    total_data.append([None, Paragraph("SGST Total", tr_r), Paragraph(f"<b>Rs.{voucher.sgst_amount:,.2f}</b>", tr_rb)])
            else:
                total_data.append([None, Paragraph("Subtotal", tr_r), Paragraph(f"<b>Rs.{voucher.taxable_amount:,.2f}</b>", tr_rb)])
            
            total_data.append([None, Paragraph("TOTAL", ParagraphStyle('gt', fontSize=13*scale, fontName='Helvetica-Bold')), 
                               Paragraph(f"<b>Rs.{voucher.total_amount:,.2f}</b>", ParagraphStyle('gt_v', fontSize=13*scale, fontName='Helvetica-Bold', alignment=TA_RIGHT))])
            
            tot_tbl = Table(total_data, colWidths=[0.45*W, 0.25*W, 0.3*W], rowHeights=[None]*(len(total_data)-1) + [7*mm*scale])
            tot_tbl.setStyle(TableStyle([
                ('LINEABOVE', (1,-1), (-1,-1), 0 if is_preprinted else 1.0, primary_c),
                ('TOPPADDING', (1,-1), (-1,-1), 4),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ]))
        
        # 5. GST Summary (Optional)
        gst_elements = []
        if getattr(company, 'show_gst_summary', True) and voucher.voucher_type in ['Sales', 'Purchase'] and not hide_gst_on_invoice:
            if is_thermal:
                gst_rows = [
                    [Paragraph("<b>GST BREAKDOWN</b>", ParagraphStyle('gst_th_title', fontSize=8*scale, fontName='Helvetica-Bold', alignment=TA_CENTER))]
                ]
                has_gst = False
                if voucher.is_igst and (voucher.igst_amount or 0) > 0:
                    gst_rows.append([Paragraph("IGST", ParagraphStyle('gst_lbl_t', parent=tr_s, textColor=colors.grey, fontSize=8*scale)), 
                                     Paragraph(f"{voucher.igst_amount:,.2f}", ParagraphStyle('gst_val_t', parent=tr_rb, textColor=colors.grey, fontSize=8*scale))])
                    has_gst = True
                else:
                    if (voucher.cgst_amount or 0) > 0:
                        gst_rows.append([Paragraph("CGST", ParagraphStyle('gst_lbl_t', parent=tr_s, textColor=colors.grey, fontSize=8*scale)), 
                                         Paragraph(f"{voucher.cgst_amount:,.2f}", ParagraphStyle('gst_val_t', parent=tr_rb, textColor=colors.grey, fontSize=8*scale))])
                        has_gst = True
                    if (voucher.sgst_amount or 0) > 0:
                        gst_rows.append([Paragraph("SGST", ParagraphStyle('gst_lbl_t', parent=tr_s, textColor=colors.grey, fontSize=8*scale)), 
                                         Paragraph(f"{voucher.sgst_amount:,.2f}", ParagraphStyle('gst_val_t', parent=tr_rb, textColor=colors.grey, fontSize=8*scale))])
                        has_gst = True
                
                if has_gst:
                    gst_tbl = Table(gst_rows, colWidths=[0.6*W, 0.4*W])
                    gst_tbl.setStyle(TableStyle([
                        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                        ('SPAN', (0,0), (-1,0)),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                        ('TOPPADDING', (0,0), (-1,-1), 2),
                        ('LEFTPADDING', (0,0), (-1,-1), 0),
                        ('RIGHTPADDING', (0,0), (-1,-1), 0),
                    ]))
                    gst_elements = [
                        Spacer(1, 3*mm), 
                        gst_tbl,
                        Spacer(1, 1.5*mm),
                        HRFlowable(width=W, thickness=0.8, color=primary_c, spaceBefore=1, spaceAfter=4, hAlign='CENTER')
                    ]
            else:
                hsn_summary = {}
                for item in voucher.items:
                    key = (item.hsn_code or '—', item.gst_rate)
                    if key not in hsn_summary:
                        hsn_summary[key] = {'taxable': 0, 'gst': 0, 'hsn': item.hsn_code or '—', 'rate': item.gst_rate}
                    hsn_summary[key]['taxable'] += (item.taxable_amount or 0)
                    hsn_summary[key]['gst'] += ((item.cgst_amount or 0) + (item.sgst_amount or 0) + (item.igst_amount or 0))
                
                if hsn_summary:
                    gst_data = [[Paragraph("HSN/SAC", th_s), Paragraph("TAXABLE", th_r), Paragraph("TAX RATE", th_r), Paragraph("GST AMOUNT", th_r)]]
                    for h in sorted(hsn_summary.values(), key=lambda x: x['hsn']):
                        gst_data.append([
                            Paragraph(h['hsn'], tr_s),
                            Paragraph(f"{h['taxable']:,.2f}", tr_r),
                            Paragraph(f"{h['rate']}%", tr_r),
                            Paragraph(f"<b>{h['gst']:,.2f}</b>", tr_rb)
                        ])
                    
                    gst_tbl = Table(gst_data, colWidths=[0.3*W, 0.25*W, 0.2*W, 0.25*W])
                    gst_tbl.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), None if is_preprinted else th_bg),
                        ('LINEABOVE', (0,0), (-1,0), 0 if is_preprinted else 0.6, primary_c),
                        ('LINEBELOW', (0,0), (-1,0), 0 if is_preprinted else 0.4, primary_c),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                        ('TOPPADDING', (0,0), (-1,-1), 2),
                    ]))
                    gst_elements = [Spacer(1, 3*mm), Paragraph("GST SUMMARY BREAKDOWN", ParagraphStyle('gst_h', fontSize=6*scale, fontName='Helvetica-Bold', spaceAfter=2)), gst_tbl]

        # 5.5 - 6. Combined Boxed Footer
        bank = get_bank_details(company)
        bank_info = []
        if bank['has_bank']:
            bank_info.append(Paragraph("<b>BANK DETAILS</b>", label_s))
            if bank['bank_name']: bank_info.append(Paragraph(f"Bank: {bank['bank_name']}", contact_style))
            if bank['bank_account']: bank_info.append(Paragraph(f"A/C: {bank['bank_account']}", contact_style))
            if bank['bank_ifsc']: bank_info.append(Paragraph(f"IFSC: {bank['bank_ifsc']}", contact_style))
            if bank['upi_id']: bank_info.append(Paragraph(f"UPI ID: {bank['upi_id']}", contact_style))
        
        terms_info = [Paragraph("<b>TERMS & CONDITIONS</b>", label_s)]
        for line in get_company_terms(company):
            terms_info.append(Paragraph(line, contact_style))

        qr_col = []
        if qr_placement != 'TOP_RIGHT':
            qr_size = 30 if is_thermal else (14 * scale)
            if getattr(company, 'show_upi_qr', True) and company.upi_id:
                qr_col.append(make_qr_image(build_upi_qr(company, voucher.total_amount), qr_size))
                qr_col.append(Paragraph("PAYMENT QR", ParagraphStyle('f8', fontSize=5*scale, alignment=TA_CENTER, textColor=colors.grey)))
            
            if getattr(company, 'show_invoice_qr', False) and getattr(company, 'enable_gst', True):
                if qr_col: qr_col.append(Spacer(1, 1*mm))
                qr_col.append(make_qr_image(build_invoice_qr(voucher, company), qr_size))
                qr_col.append(Paragraph("INVOICE QR", ParagraphStyle('f8', fontSize=5*scale, alignment=TA_CENTER, textColor=colors.grey)))

        sig_col = []
        sig_img = build_signature_image(company, width_mm=26*scale)
        if sig_img:
            sig_col.append(sig_img)
        else:
            sig_col.append(Spacer(1, 6*mm*scale))
        sig_col.append(Paragraph("AUTHORIZED SIGNATORY", ParagraphStyle('f_lbl', fontSize=5*scale, textColor=colors.grey, alignment=TA_RIGHT)))
        sig_col.append(Paragraph(f"<b>{company.name.upper()}</b>", ParagraphStyle('f_co', fontSize=7*scale, fontName='Helvetica-Bold', alignment=TA_RIGHT)))

        if is_thermal:
            thermal_footer = []
            
            # 1. QR Code / Scan to pay
            if qr_col:
                thermal_footer.append(Spacer(1, 2*mm))
                for q_el in qr_col:
                    if isinstance(q_el, RLImage):
                        q_el.hAlign = 'CENTER'
                    elif isinstance(q_el, Paragraph):
                        q_el.style.alignment = TA_CENTER
                    thermal_footer.append(q_el)
            
            # 2. Bank Details
            if bank['has_bank']:
                thermal_footer.append(Spacer(1, 3*mm))
                thermal_footer.append(Paragraph("<b>BANK DETAILS</b>", ParagraphStyle('b_lbl_t', parent=label_s, alignment=TA_CENTER)))
                if bank['bank_name']: thermal_footer.append(Paragraph(f"Bank: {bank['bank_name']}", ParagraphStyle('b1_t', parent=contact_style, alignment=TA_CENTER)))
                if bank['bank_account']: thermal_footer.append(Paragraph(f"A/C: {bank['bank_account']}", ParagraphStyle('b2_t', parent=contact_style, alignment=TA_CENTER)))
                if bank['bank_ifsc']: thermal_footer.append(Paragraph(f"IFSC: {bank['bank_ifsc']}", ParagraphStyle('b3_t', parent=contact_style, alignment=TA_CENTER)))
                if bank['upi_id']: thermal_footer.append(Paragraph(f"UPI ID: {bank['upi_id']}", ParagraphStyle('b4_t', parent=contact_style, alignment=TA_CENTER)))
            
            # 3. Terms & Conditions
            if company.terms or get_company_terms(company):
                thermal_footer.append(Spacer(1, 3*mm))
                thermal_footer.append(Paragraph("<b>TERMS & CONDITIONS</b>", ParagraphStyle('t_lbl_t', parent=label_s, alignment=TA_CENTER)))
                for line in get_company_terms(company):
                    thermal_footer.append(Paragraph(line, ParagraphStyle('t_val_t', parent=contact_style, alignment=TA_LEFT)))
            
            # 4. Signature block
            thermal_footer.append(Spacer(1, 4*mm))
            sig_col_t = []
            if sig_img:
                sig_img.hAlign = 'CENTER'
                sig_col_t.append(sig_img)
                sig_col_t.append(Spacer(1, 1*mm))
            sig_col_t.append(Paragraph("AUTHORIZED SIGNATORY", ParagraphStyle('f_lbl_t', fontSize=5*scale, textColor=colors.grey, alignment=TA_CENTER)))
            sig_col_t.append(Paragraph(f"<b>{company.name.upper()}</b>", ParagraphStyle('f_co_t', fontSize=7*scale, fontName='Helvetica-Bold', alignment=TA_CENTER)))
            thermal_footer.extend(sig_col_t)
            
            f_tbl_elements = thermal_footer
        else:
            if qr_placement == 'BOTTOM_LEFT':
                bank_info.append(Spacer(1, 2*mm))
                bank_info.extend(qr_col)
                qr_col = []
            elif qr_placement == 'BOTTOM_RIGHT':
                sig_col.insert(0, Spacer(1, 2*mm))
                for item in reversed(qr_col):
                    sig_col.insert(0, item)
                qr_col = []

            footer_data = [
                [bank_info, qr_col, terms_info, sig_col]
            ]
            
            f_tbl = Table(footer_data, colWidths=[0.35*W, 0.15*W, 0.3*W, 0.2*W])
            f_tbl.setStyle(TableStyle([
                ('BOX', (0,0), (-1,-1), 0.5, primary_c),
                ('LINEAFTER', (1,0), (1,-1), 0.25, colors.lightgrey),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('TOPPADDING', (0,0), (-1,-1), 2),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ('ALIGN', (0,0), (0,0), 'LEFT'),
                ('ALIGN', (1,0), (1,0), 'CENTER'),
                ('ALIGN', (2,0), (2,0), 'LEFT'),
                ('ALIGN', (3,0), (3,0), 'RIGHT'),
            ]))
            f_tbl_elements = [Spacer(1, 3*mm), f_tbl]
        
        # ── Dynamic Drag & Drop Block Assembly ────────────────
        blocks = {
            'header': hdr_flowables,
            'hr': hr_flowables,
            'addresses': [info_tbl, Spacer(1, 1.5*mm), HRFlowable(width=W, thickness=0.8, color=primary_c, spaceBefore=1, spaceAfter=4, hAlign='CENTER')] if is_thermal else [info_tbl, Spacer(1, 6*mm)],
            'items': [item_tbl, Spacer(1, 1.5*mm)] if is_thermal else [item_tbl, Spacer(1, 5*mm)],
            'totals': [tot_tbl],
            'gst': gst_elements,
            'footer': f_tbl_elements
        }

        block_order_str = getattr(company, 'block_order', 'header,hr,addresses,items,totals,gst,footer') or 'header,hr,addresses,items,totals,gst,footer'
        for b_key in block_order_str.split(','):
            b_key = b_key.strip()
            if b_key in blocks:
                for flowable in blocks[b_key]:
                    story.append(flowable)

        if voucher.narration:
            story.append(Spacer(1, 1*mm))
            story.append(Paragraph(f"<b>NARRATION:</b> {voucher.narration}", contact_style))

        footer_note = ctexts['footer'] or "THANK YOU! VISIT AGAIN"
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(f"<b>{footer_note.upper()}</b>", ParagraphStyle('cft', fontSize=8*scale, alignment=TA_CENTER, textColor=primary_c)))

        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("This is a Computer Generated Invoice", ParagraphStyle('f', fontSize=6, alignment=TA_CENTER, textColor=colors.grey)))

        if copy_idx < num_copies - 1:
            story.append(PageBreak())

    doc.watermark_path = getattr(company, 'watermark_path', None)
    doc.build(story, onFirstPage=draw_watermark, onLaterPages=draw_watermark)
    buffer.seek(0)
    return buffer.getvalue()

