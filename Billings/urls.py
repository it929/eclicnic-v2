from django.urls import path
from . import views

urlpatterns = [

    # Queue within 24 hours
    path('transactions', views.get_transactions, name="get_transactions"),
    path('partially-paid-transactions', views.get_partially_paid_transactions, name="get_partially_paid_transactions"),
    path('completed-transactions', views.get_completed_transactions, name="get_completed_transactions"),
    path('transactions-table', views.get_transactions_table, name="get_transactions_table"),

    # Queue Older than 24 hours
    path('transactions-all', views.get_transactions_all, name="get_transactions_all"),
    path('partially-paid-transactions-all', views.get_partially_paid_transactions_all, name="get_partially_paid_transactions_all"),
    path('completed-transactions-all', views.get_completed_transactions_all, name="get_completed_transactions_all"),
    path('transactions-table-all', views.get_transactions_table_all, name="get_transactions_table_all"),

    # Transaction Day Book
    path('day-book/', views.transaction_day_book, name='transaction_day_book'),
    path('api/patients/search/', views.patient_search_api, name='patient_search_api'),

    # Items Billing
    path('total-billings/<int:patient_id>/', views.get_billings, name='get_billings'),
    path('patient/<int:patient_id>/billings/', views.get_billings, name='get_billings'),
    path('patient/<int:patient_id>/clear_transactions/', views.clear_transactions, name='clear_transactions'),

    # Transaction Invoice
    path('patient/<int:patient_id>/create_invoice/', views.create_invoice, name='create_invoice'),
    path('patient/<int:patient_id>/reset_invoice/', views.reset_invoice, name='reset_invoice'),
    path('total-invoice/<int:patient_id>/', views.get_invoice, name='get_invoice'),
    path('save-signature/', views.save_signature, name='save_signature'),
    path('send-qr-code/', views.send_qr_code, name='send_qr_code'),
    path('download-invoice/<str:invoice_number>/<str:format>/', views.download_invoice, name='download_invoice'),
    
    # Transaction Receipt
    path('patient/<int:patient_id>/create-receipt/', views.create_receipt, name='create_receipt'),
    path('patient/<int:patient_id>/create-receipt-all/', views.create_receipt_general, name='non_categorized_payment'),
    path('total-receipt/<int:patient_id>/', views.get_receipt, name='get_receipt'),
    path('save-receipt-signature/', views.save_receipt_signature, name='save_receipt_signature'),
    path('send-receipt-qr-code/', views.send_receipt_qr_code, name='send_receipt_qr_code'),
    path('download-receipt/<str:receipt_number>/<str:format>/', views.download_receipt, name='download_receipt'),

    # Account Statements
    path('get-statements/<int:patient_id>/', views.get_statements, name='get_statements'),
    path('email-statement/<int:patient_id>/', views.email_statement, name='email_statement'),

    # Account Summary
    path('get-summary/<int:patient_id>/', views.get_summary, name='get_summary'),
    path('export-summary-excel/<int:patient_id>/', views.export_summary_excel, name='export_summary_excel'),


    # Deposit & Refund
    path('<int:patient_id>/create/', views.create_deposit_refund, name='create_deposit_refund'),

    # Deposits
    path('<int:patient_id>/deposits/', views.list_deposits, name='list_deposits'),
    path('<int:patient_id>/deposits/<int:deposit_id>/', views.deposit_detail, name='deposit_detail'),
    path('<int:patient_id>/deposits/<int:deposit_id>/delete/', views.delete_deposit, name='delete_deposit'),

    # Refunds
    path('<int:patient_id>/refunds/', views.list_refunds, name='list_refunds'),
    path('<int:patient_id>/refunds/<int:refund_id>/', views.refund_detail, name='refund_detail'),
    path('<int:patient_id>/refunds/<int:refund_id>/delete/', views.delete_refund, name='delete_refund'),

]