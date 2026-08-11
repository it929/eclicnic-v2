from django.urls import path
from. import views

urlpatterns = [
    # Ambulatory
    path('reports/ambulatory/', views.ambulatory_patient_report, name='ambulatory_report'),
    path('reports/ambulatory-visit/', views.ambulatory_visit_report, name='ambulatory_visit_report'),
    path('admission-records/', views.admission_records_report, name='admission_records_report'),
    path('deactivated-patients-report/', views.deactivated_patients_report, name='deactivated_patients_report'),

    # Billings
    path('reports/billing-invoice/', views.billing_invoice_listing, name='billing_invoice_listing'),
    path('reports/transaction-book/', views.transaction_book_report, name='transaction_book_report'),
    path('exception-bills/', views.exception_bills_report, name='exception_bills_report'),
    path('cancelled-transactions/', views.cancelled_transactions_report, name='cancelled_transactions_report'),
    
    # Inventory and Pharmacies
    path('expired-products/', views.expired_products_report, name='expired_products_report'),
    path('expiring-products/', views.expiring_products_report, name='expiring_products_report'),
    path('low-stock-products/', views.low_stock_products_report, name='low_stock_products_report'),
    path('out-of-stock-products/', views.out_of_stock_products_report, name='out_of_stock_products_report'),
    path('report/product-requisition/', views.product_requisition_report, name='product_requisition_report'),
    path('stock-analysis/', views.stock_analysis_report, name='stock_analysis_report'),
    path('vendors-expense-analysis/', views.vendors_expense_analysis_report, name='vendors_expense_analysis_report'),

    # General
    path('report/patient-search/', views.patient_search_api_report, name='patient_search_api_report'),

]