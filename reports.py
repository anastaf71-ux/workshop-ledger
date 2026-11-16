"""Printable Arabic RTL customer statements and machining work orders.

These functions only produce HTML. They never modify the database and can be
unit-tested even on a Linux server without Qt or a printer.
"""
from html import escape
from datetime import datetime


def e(value) -> str:
    return escape(str(value if value is not None else ''), quote=True)


def money(cents: int, currency='USD') -> str:
    return f'{cents / 100:,.2f} {e(currency)}'


def date_text(value) -> str:
    try:
        return datetime.fromisoformat(value).strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return str(value or '')


def shell(title: str, subtitle: str, body: str) -> str:
    return f'''<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
    <title>{e(title)}</title><style>
    body{{font-family:'Segoe UI',Tahoma,Arial,sans-serif;color:#20344a;direction:rtl;font-size:12px;}}
    .heading{{padding:16px 0;border-bottom:3px solid #1b5684;}}
    h1{{font-size:23px;margin:0 0 6px;}} .sub{{color:#61758b;}}
    table{{border-collapse:collapse;width:100%;margin:15px 0;}}
    th{{background:#eaf2fa;color:#203c58;text-align:right;padding:8px;border:1px solid #c5d5e4;}}
    td{{padding:8px;border:1px solid #d4dce5;vertical-align:top;}}
    tr:nth-child(even) td{{background:#f8fafc;}}
    .facts{{margin:15px 0;line-height:2;}} .total{{font-weight:700;background:#eaf2fa;padding:14px;}}
    .foot{{font-size:10px;color:#718197;padding:20px 0;border-top:1px solid #dce4ed;}}
    .num{{direction:ltr;unicode-bidi:embed;white-space:nowrap;}}
    </style></head><body>
    <div class="heading"><h1>{e(title)}</h1><div class="sub">{e(subtitle)}</div></div>
    {body}<div class="foot">Workshop Ledger • نسخة للاطلاع والطباعة • تاريخ الطباعة {datetime.now().strftime('%Y-%m-%d')}</div>
    </body></html>'''


def customer_statement_html(db, customer_id: int, currency='USD') -> str:
    customer = db.get_customer(customer_id)
    if not customer:
        raise ValueError('Customer not found.')
    entries = db.customer_statement(customer_id)
    t = db.customer_account_totals(customer_id)
    names = {'charge':'أشغال مستحقة','opening_debt':'رصيد قديم',
             'payment':'دفعة مقبوضة','discount':'خصم ممنوح',
             'opening_discount':'تسوية رصيد قديم'}
    rows=[]
    for row in entries:
        due = row['amount_cents'] if row['kind'] in ('charge','opening_debt') else 0
        reduction = row['amount_cents'] if not due else 0
        rows.append(f'<tr><td>{e(date_text(row["created_at"]))}</td>'
            f'<td>{e(names.get(row["kind"],row["kind"]))}</td>'
            f'<td>{e(row["description"])}</td><td class="num">{money(due,currency) if due else "—"}</td>'
            f'<td class="num">{money(reduction,currency) if reduction else "—"}</td>'
            f'<td class="num">{money(row["running_due_cents"],currency)}</td></tr>')
    state = 'مسدّد بالكامل' if t['due_cents']==0 else 'رصيد دائن' if t['due_cents']<0 else 'مبلغ مستحق'
    body=(f'<div class="facts"><b>رقم الزبون:</b> {customer_id} &nbsp; '
          f'<b>الاسم:</b> {e(customer["name"])} &nbsp; <b>الهاتف:</b> {e(customer["phone"] or "—")}</div>'
          '<table><thead><tr><th>التاريخ</th><th>نوع الحركة</th><th>البيان</th>'
          '<th>مطلوب</th><th>تسديد / خصم</th><th>الرصيد</th></tr></thead><tbody>'
          +''.join(rows)+'</tbody></table>'
          f'<div class="total">مجموع الأشغال: {money(t["billed_cents"],currency)} &nbsp; '
          f'رصيد سابق: {money(t["opening_cents"],currency)} &nbsp; '
          f'المقبوض: {money(t["paid_cents"],currency)} &nbsp; '
          f'الخصومات: {money(t["discount_cents"]+t["opening_discount_cents"],currency)}'
          f'<p>المتبقي: {money(t["due_cents"],currency)} — {state}</p></div>')
    return shell('كشف حساب الزبون', f'كشف الحساب رقم {customer_id}', body)


def work_order_html(db, order_id: int, currency='USD') -> str:
    order=db.get_work_order(order_id)
    if not order:
        raise ValueError('Work order not found.')
    customer=db.get_customer(order['customer_id'])
    lines=db.list_work_order_lines(order_id)
    rows=[]
    total=0
    for n,row in enumerate(lines,1):
        total+=row['total_cents']
        rows.append(f'<tr><td>{n}</td><td>{e(row["description"])}</td>'
                    f'<td>{row["qty"]}</td><td class="num">{money(row["unit_price_cents"],currency)}</td>'
                    f'<td class="num">{money(row["total_cents"],currency)}</td></tr>')
    cyl = str(order['cylinder_count']) if order['cylinder_count'] else 'غير محدد'
    body=(f'<div class="facts"><b>رقم أمر الشغل:</b> {order_id} &nbsp; '
          f'<b>التاريخ:</b> {e(date_text(order["created_at"]))}<p>'
          f'<b>اسم الزبون:</b> {e(customer["name"])} &nbsp; '
          f'<b>الهاتف:</b> {e(customer["phone"] or "—")}</p><p>'
          f'<b>نوع المحرك:</b> {e(order["engine_model"])} &nbsp; '
          f'<b>عدد السلندرات:</b> {cyl} &nbsp; '
          f'<b>السيارة / الآلة:</b> {e(order["vehicle"] or "—")}</p><p>'
          f'<b>رقم المحرك:</b> {e(order["engine_number"] or "—")} &nbsp; '
          f'<b>الحالة:</b> {e(order["status"])} &nbsp; '
          f'<b>الفاتورة:</b> {"مرحّلة إلى الحساب" if order["billed_at"] else "مسودة غير مرحّلة"}</p></div>'
          '<table><thead><tr><th>#</th><th>العملية</th><th>العدد</th>'
          '<th>سعر الوحدة</th><th>المجموع</th></tr></thead><tbody>'+''.join(rows)
          +'</tbody></table>'
          f'<div class="total">إجمالي الأشغال: {money(total,currency)}</div>'
          f'<p><b>ملاحظات المحرك:</b> {e(order["notes"] or "—")}</p>'
          '<p style="margin-top:35px">توقيع العامل: ________________ &nbsp; توقيع المستلم: ________________</p>')
    return shell('أمر شغل محرك', f'دفتر الأشغال / أمر رقم {order_id}',body)
