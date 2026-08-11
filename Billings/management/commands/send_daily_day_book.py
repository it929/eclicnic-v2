import os
import sys
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from io import BytesIO
from collections import defaultdict

class Command(BaseCommand):
    help = 'Send daily day book report to CMD at 11pm WAT'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Override recipient email address',
        )
        parser.add_argument(
            '--test',
            action='store_true',
            help='Send test report for debugging',
        )

    def handle(self, *args, **options):
        # Set timezone to WAT (UTC+1)
        wat_timezone = timezone.get_current_timezone()
        now = timezone.now()
        
        if options.get('test'):
            # Test mode: send report for last 24 hours
            start_datetime = now - timedelta(hours=24)
            end_datetime = now
            self.stdout.write("TEST MODE: Sending test report")
        else:
            # Production: 11pm yesterday to 11pm today
            today_11pm = now.replace(hour=23, minute=0, second=0, microsecond=0)
            if now >= today_11pm:
                # After 11pm today
                yesterday_11pm = today_11pm - timedelta(days=1)
                start_datetime = yesterday_11pm
                end_datetime = today_11pm
            else:
                # Before 11pm today, send previous day's report
                yesterday_11pm = (now - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
                start_datetime = yesterday_11pm
                end_datetime = yesterday_11pm + timedelta(hours=24)
        
        self.stdout.write(f"Generating report for period: {start_datetime} to {end_datetime}")
        
        # Get recipient email
        recipient_email = options.get('email') or 'adebayoseun109@gmail.com'
        
        try:
            # Generate report data
            report_data = self.generate_report_data(start_datetime, end_datetime)
            
            # Generate PDF
            pdf_content = self.generate_pdf(report_data, start_datetime, end_datetime)
            
            # Send email
            self.send_email(pdf_content, recipient_email, start_datetime, end_datetime, report_data)
            
            self.stdout.write(self.style.SUCCESS(
                f"Daily day book report sent successfully to {recipient_email}"
            ))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error generating report: {str(e)}"))
            if options.get('test'):
                import traceback
                traceback.print_exc()
    
    def generate_report_data(self, start_datetime, end_datetime):
        """Generate the day book data for the given period"""
        from Billings.models import Invoice, Receipt, Refund
        from django.db.models import Sum
        
        # Get invoices within the period
        invoices = Invoice.objects.filter(
            price__gt=0,
            created_date__gte=start_datetime,
            created_date__lte=end_datetime
        ).select_related('patient', 'category')
        
        # Group by invoice number
        grouped_invoices = defaultdict(lambda: {
            'date': None,
            'patient': None,
            'patient_id': None,
            'details': set(),
            'total_revenue': 0,
            'collections': 0,
            'refunds': 0,
            'invoice_number': None
        })
        
        for invoice in invoices:
            inv_num = invoice.invoice_number
            
            if not grouped_invoices[inv_num]['invoice_number']:
                grouped_invoices[inv_num]['invoice_number'] = inv_num
                grouped_invoices[inv_num]['date'] = invoice.created_date
                
                if invoice.patient:
                    patient_name = invoice.patient.get_full_name() if hasattr(invoice.patient, 'get_full_name') else f"{invoice.patient.surname} {invoice.patient.first_name}"
                    patient_id = invoice.patient.hospital_number
                    grouped_invoices[inv_num]['patient'] = patient_name
                    grouped_invoices[inv_num]['patient_id'] = patient_id
                else:
                    grouped_invoices[inv_num]['patient'] = 'N/A'
                    grouped_invoices[inv_num]['patient_id'] = 'N/A'
            
            details = self.get_details_from_source_model(invoice.original_source_model)
            grouped_invoices[inv_num]['details'].add(details)
            grouped_invoices[inv_num]['total_revenue'] += invoice.price
        
        # Get collections and refunds
        for inv_num in grouped_invoices.keys():
            receipts = Receipt.objects.filter(invoice_number__iexact=inv_num)
            collections = receipts.aggregate(total=Sum('total_price'))['total'] or 0
            grouped_invoices[inv_num]['collections'] = collections
            
            refunds = Refund.objects.filter(invoice_id__iexact=inv_num)
            refund_amount = refunds.aggregate(total=Sum('amount'))['total'] or 0
            grouped_invoices[inv_num]['refunds'] = refund_amount
        
        # Prepare final entries
        day_book_entries = []
        total_revenues = 0
        total_collections = 0
        total_refunds = 0
        total_balance = 0
        
        for inv_num, data in grouped_invoices.items():
            balance = data['total_revenue'] - data['collections']
            
            details_list = sorted(list(data['details']))
            details_text = ', '.join(details_list)
            
            entry = {
                'date': data['date'].strftime('%d %b %Y') if data['date'] else '',
                'patient': data['patient'],
                'patient_id': data['patient_id'],
                'details': details_text,
                'revenue': data['total_revenue'],
                'collections': data['collections'],
                'refunds': data['refunds'],
                'balance': balance,
            }
            
            day_book_entries.append(entry)
            
            total_revenues += data['total_revenue']
            total_collections += data['collections']
            total_refunds += data['refunds']
            total_balance += balance
        
        # Sort by date
        day_book_entries.sort(key=lambda x: x['date'], reverse=True)
        
        return {
            'day_book_entries': day_book_entries,
            'total_revenues': total_revenues,
            'total_collections': total_collections,
            'total_refunds': total_refunds,
            'total_balance': total_balance,
            'entries_count': len(day_book_entries),
        }
    
    def get_details_from_source_model(self, source_model):
        """Map source model to details text"""
        if not source_model:
            return 'Services'
        
        medication_models = [
            'IPDAdministeredDrugs', 'IPD2AdministeredDrugs',
            'IPD3AdministeredDrugs', 'OPDAdministeredDrugs',
            'OPD2AdministeredDrugs'
        ]
        
        if source_model in medication_models:
            return 'Medication'
        elif source_model == 'RadiologyLab':
            return 'Investigations'
        elif source_model == 'NurseWaitingList':
            return 'Consultation'
        elif source_model == 'OtherService':
            return 'Services'
        elif source_model == 'AdmissionFee':
            return 'Admission'
        elif source_model == 'GetRegistrationFee':
            return 'Registration'
        else:
            return 'Services'
    
    def generate_pdf(self, report_data, start_datetime, end_datetime):
        """Generate PDF from HTML template"""
        try:
            from xhtml2pdf import pisa
            from django.template.loader import get_template
            
            context = {
                'day_book_entries': report_data['day_book_entries'],
                'total_revenues': report_data['total_revenues'],
                'total_collections': report_data['total_collections'],
                'total_refunds': report_data['total_refunds'],
                'total_balance': report_data['total_balance'],
                'start_datetime': start_datetime,
                'end_datetime': end_datetime,
                'generated_on': timezone.now(),
                'company_name': getattr(settings, 'COMPANY_NAME', 'Healthcare Facility'),
            }
            
            template = get_template('Billings/day_book_pdf.html')
            html_string = template.render(context)
            
            result = BytesIO()
            pdf = pisa.pisaDocument(BytesIO(html_string.encode('UTF-8')), result)
            
            if not pdf.err:
                return result.getvalue()
            else:
                self.stdout.write(self.style.ERROR('PDF generation failed'))
                return None
                
        except ImportError:
            self.stdout.write(self.style.WARNING('xhtml2pdf not installed. Installing...'))
            self.stdout.write('Run: pip install xhtml2pdf reportlab')
            return None
    
    def send_email(self, pdf_content, recipient_email, start_datetime, end_datetime, report_data):
        """Send email with PDF attachment"""
        subject = f"Daily Day Book Report - {start_datetime.strftime('%d %b %Y')}"
        
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .summary {{
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 15px 0;
                }}
                .summary-item {{ margin: 10px 0; }}
                .positive {{ color: #28a745; font-weight: bold; }}
                .negative {{ color: #dc3545; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h2>Daily Day Book Report</h2>
            <p>Dear CMD,</p>
            <p>Please find attached the daily transaction day book report for:</p>
            <p><strong>{start_datetime.strftime('%d %b %Y, %I:%M %p')} to {end_datetime.strftime('%d %b %Y, %I:%M %p')}</strong></p>
            
            <div class="summary">
                <div class="summary-item">📊 <strong>Total Transactions:</strong> {report_data['entries_count']}</div>
                <div class="summary-item">💰 <strong>Total Revenues:</strong> <span class="positive">₦{report_data['total_revenues']:,.2f}</span></div>
                <div class="summary-item">💵 <strong>Total Collections:</strong> <span class="positive">₦{report_data['total_collections']:,.2f}</span></div>
                <div class="summary-item">↩️ <strong>Total Refunds:</strong> <span class="negative">₦{report_data['total_refunds']:,.2f}</span></div>
                <div class="summary-item">⚖️ <strong>Outstanding Balance:</strong> 
                    <span class="{'positive' if report_data['total_balance'] > 0 else 'negative'}">
                        ₦{report_data['total_balance']:,.2f}
                    </span>
                </div>
            </div>
            
            <p>This is an automated daily report generated by the system.</p>
            <hr>
            <p style="font-size: 12px; color: #777;">
                This email was automatically generated by the Hospital Management System.<br>
                Please do not reply to this email.
            </p>
        </body>
        </html>
        """
        
        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
        )
        email.content_subtype = 'html'
        
        if pdf_content:
            email.attach(
                f"Daily_Day_Book_{start_datetime.strftime('%Y%m%d')}.pdf",
                pdf_content,
                'application/pdf'
            )
        
        email.send(fail_silently=False)