from django.urls import path
from . import views

urlpatterns = [


    path('inventory', views.add_product, name = "add_product"),
    path('upload-products/', views.upload_products_from_excel, name='upload_products'),
    path('product-format', views.download_import_template, name = "download_product_format"),
    path('vendor-format', views.download_vendors_import_template, name = "download_vendor_format"),
    path('stock', views.generate_report, name = "stock"),
    path('stock-stock', views.out_stock_report, name = "out_stock"),
    path('update-inventory/<str:product_id>/', views.update_stock, name = "update_stock"),

    path('scan-barcode/', views.barcodeScan, name="scan_barcode"),
 
    # Export product to IPD Pharmacy
    path("export-to-ipd/", views.upload_to_ipdpharm, name="upload_to_ipd"),
    path("export-to-ipd2/", views.upload_to_ipd2pharm, name="upload_to_ipd2"),
    path("export-to-ipd3/", views.upload_to_ipd3pharm, name="upload_to_ipd3"),
    path("export-to-opd/", views.upload_to_opdpharm, name="upload_to_opd"),
    path("export-to-opd2/", views.upload_to_opd2pharm, name="upload_to_opd2"),
 
    path('api/product-search2/', views.product_search_api2, name='product_search_api'),
    # path('save-administered-drugs/', views.save_administered_drugs, name='save_administered_drugs'),
    
    path("save-inventory-transaction/", views.save_inventory_export_transaction, name="save_inventory_transaction"),
    path("save-ipd-transaction/", views.save_ipd_export_transaction, name="save_ipd_transaction"),
    path("save-ipd2-transaction/", views.save_ipd2_export_transaction, name="save_ipd2_transaction"),
    path("save-ipd3-transaction/", views.save_ipd3_export_transaction, name="save_ipd3_transaction"),
    path("save-opd-transaction/", views.save_opd_export_transaction, name="save_opd_transaction"),
    path("save-opd2-transaction/", views.save_opd2_export_transaction, name="save_opd2_transaction"),

    # Manage Exported IPD Pharmacy 1 products
    path('manage-exports-ipd/', views.manage_exported_ipd, name='manage_exports_ipd'),
    path('delete-exported-ipd/<int:product_id>/', views.delete_exported_ipd_products, name='delete_exported_ipd'),
    path('edit-exported-ipd/<int:product_id>/', views.edit_exported_ipd_products, name='edit_exported_ipd'),

    # Manage Exported IPD Pharmacy 2 products
    path('manage-exports-ipd2/', views.manage_exported_ipd2, name='manage_exports_ipd2'),
    path('delete-exported-ipd2/<int:product_id>/', views.delete_exported_ipd2_products, name='delete_exported_ipd2'),
    path('edit-exported-ipd2/<int:product_id>/', views.edit_exported_ipd2_products, name='edit_exported_ipd2'),

    # Manage Exported IPD Pharmacy 3 products
    path('manage-exports-ipd3/', views.manage_exported_ipd3, name='manage_exports_ipd3'),
    path('delete-exported-ipd3/<int:product_id>/', views.delete_exported_ipd3_products, name='delete_exported_ipd3'),
    path('edit-exported-ipd3/<int:product_id>/', views.edit_exported_ipd3_products, name='edit_exported_ipd3'),

    # Manage Exported OPD Pharmacy 1 products
    path('manage-exports-opd/', views.manage_exported_opd, name='manage_exports_opd'),
    path('delete-exported-opd/<int:product_id>/', views.delete_exported_opd_products, name='delete_exported_opd'),
    path('edit-exported-opd/<int:product_id>/', views.edit_exported_opd_products, name='edit_exported_opd'),

    # Manage Exported OPD Pharmacy 2 products
    path('manage-exports-opd2/', views.manage_exported_opd2, name='manage_exports_opd2'),
    path('delete-exported-opd2/<int:product_id>/', views.delete_exported_opd2_products, name='delete_exported_opd2'),
    path('edit-exported-opd2/<int:product_id>/', views.edit_exported_opd2_products, name='edit_exported_opd2'),

    # Imports
    path('manage-imports/', views.manage_imported_product, name='manage_imports'),
    path('delete-imported-goods/<int:product_id>/', views.delete_imported_products, name='delete_imported_goods'),
    path('edit-imported-goods/<int:product_id>/', views.edit_imported_products, name='edit_imported_goods'),

    
    # Histories
    path('imports-history', views.imports_history, name='imports_history'),
    path('exports-history', views.exports_history, name='exports_history'),
    path('requests-history', views.requests_history, name='requests_history'),


    # Vendors
    path('view-vendors', views.view_vendors, name='view_vendors'),
    path('manage-vendors/<str:vendor_id>/', views.manage_vendors, name='manage_vendors'),
    path('create-vendors', views.create_vendors_records, name='create_vendors_records'),

     # ---------- IPD Pharmacy 1 --------------

    # IPD Pharmacy 1 requests to Inventory
    path('manage-ipd-requests/', views.manage_ipd1_requests, name='manage_ipd_requests'),
    path('approve-ipd-request/<int:pk>/', views.approve_ipd_request, name='approve_ipd_request'),
    path('approve-all-ipd/', views.approve_all_ipd_requests, name='approve_all_ipd'),
    path('decline-ipd-request/<int:pk>/', views.decline_ipd_request, name='decline_ipd_request'),

    # Inventory Requests to IPD Pharmacy 1
    path('ipd1/product-search2/', views.product_search_ipd1, name='product_search_ipd1'),
    path('save-ipd1-form/', views.save_inventory_to_ipd1_requisition_form, name='save_inventory_to_ipd1_requisition_form'),
    path('delete-inventory-to-ipd1-products/<int:product_id>/', views.delete_requested_inventory_to_ipd1_products, name='delete_requested_inventory_to_ipd1_products'),
    path('edit-inventory-to-ipd1-products/<int:product_id>/', views.edit_requested_inventory_to_ipd1_products, name='edit_requested_inventory_to_ipd1_products'),

    # ---------- IPD Pharmacy 2 --------------
 
    # IPD Pharmacy 2 requests to Inventory
    path('manage-ipd2-requests/', views.manage_ipd2_requests, name='manage_ipd2_requests'),
    path('approve-ipd2-request/<int:pk>/', views.approve_ipd2_request, name='approve_ipd2_request'),
    path('approve-all-ipd2/', views.approve_all_ipd2_requests, name='approve_all_ipd2'),
    path('decline-ipd2-request/<int:pk>/', views.decline_ipd2_request, name='decline_ipd2_request'),

     # Inventory Requests to IPD Pharmacy 2
    path('ipd2/product-search2/', views.product_search_ipd2, name='product_search_ipd2'),
    path('save-ipd2-form/', views.save_inventory_to_ipd2_requisition_form, name='save_inventory_to_ipd2_requisition_form'),
    path('delete-inventory-to-ipd2-products/<int:product_id>/', views.delete_requested_inventory_to_ipd2_products, name='delete_requested_inventory_to_ipd2_products'),
    path('edit-inventory-to-ipd2-products/<int:product_id>/', views.edit_requested_inventory_to_ipd2_products, name='edit_requested_inventory_to_ipd2_products'),


    # ---------- IPD Pharmacy 3 --------------
 
    # IPD Pharmacy 3 requests to Inventory
    path('manage-ipd3-requests/', views.manage_ipd3_requests, name='manage_ipd3_requests'),
    path('approve-ipd3-request/<int:pk>/', views.approve_ipd3_request, name='approve_ipd3_request'),
    path('approve-all-ipd3/', views.approve_all_ipd3_requests, name='approve_all_ipd3'),
    path('decline-ipd3-request/<int:pk>/', views.decline_ipd3_request, name='decline_ipd3_request'),

     # Inventory Requests to IPD Pharmacy 3
    path('ipd3/product-search2/', views.product_search_ipd3, name='product_search_ipd3'),
    path('save-ipd3-form/', views.save_inventory_to_ipd3_requisition_form, name='save_inventory_to_ipd3_requisition_form'),
    path('delete-inventory-to-ipd3-products/<int:product_id>/', views.delete_requested_inventory_to_ipd3_products, name='delete_requested_inventory_to_ipd3_products'),
    path('edit-inventory-to-ipd3-products/<int:product_id>/', views.edit_requested_inventory_to_ipd3_products, name='edit_requested_inventory_to_ipd3_products'),

     # ---------- OPD Pharmacy  --------------
 
    # OPD Pharmacy  requests to Inventory
    path('manage-opd-requests/', views.manage_opd_requests, name='manage_opd_requests'),
    path('approve-opd-request/<int:pk>/', views.approve_opd_request, name='approve_opd_request'),
    path('approve-all-opd/', views.approve_all_opd_requests, name='approve_all_opd'),
    path('decline-opd-request/<int:pk>/', views.decline_opd_request, name='decline_opd_request'),

     # Inventory Requests to OPD Pharmacy 1
    path('opd/product-search/', views.product_search_opd, name='product_search_opd'),
    path('save-opd-form/', views.save_inventory_to_opd_requisition_form, name='save_inventory_to_opd_requisition_form'),
    path('delete-inventory-to-opd-products/<int:product_id>/', views.delete_requested_inventory_to_opd_products, name='delete_requested_inventory_to_opd_products'),
    path('edit-inventory-to-opd-products/<int:product_id>/', views.edit_requested_inventory_to_opd_products, name='edit_requested_inventory_to_opd_products'),


    # ---------- OPD Pharmacy 2 --------------
 
    # OPD Pharmacy 2 requests to Inventory
    path('manage-opd2-requests/', views.manage_opd2_requests, name='manage_opd2_requests'),
    path('approve-opd2-request/<int:pk>/', views.approve_opd2_request, name='approve_opd2_request'),
    path('approve-all-opd2/', views.approve_all_opd2_requests, name='approve_all_opd2'),
    path('decline-opd2-request/<int:pk>/', views.decline_opd2_request, name='decline_opd2_request'),

     # Inventory Requests to OPD Pharmacy 2
    path('opd2/product-search/', views.product_search_opd2, name='product_search_opd2'),
    path('save-opd2-form/', views.save_inventory_to_opd2_requisition_form, name='save_inventory_to_opd2_requisition_form'),
    path('delete-inventory-to-opd2-products/<int:product_id>/', views.delete_requested_inventory_to_opd2_products, name='delete_requested_inventory_to_opd2_products'),
    path('edit-inventory-to-opd2-products/<int:product_id>/', views.edit_requested_inventory_to_opd2_products, name='edit_requested_inventory_to_opd2_products'),


]
