from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    path('create-account', views.create_user, name="create_account"),
    path('check-department/<int:department_id>/', views.check_department, name='check_department'),
    path('', views.user_login, name="login"),
    path('user-profile/<str:key>/', views.user_profile, name = "user-profile"),
    path('registered-user/<str:key>/', views.get_reg_users, name = "registered_user"),
    path('profile-update/<str:key>/', views.update_profile, name = "profile-update"),
    path('change-password', views.MyPasswordChangeView.as_view(), name = "change-password"),
    path('change-password/done/', views.MyPasswordResetDoneView.as_view(), name = "password-change-done"),
    path('logout/', views.user_logout, name="logout"),
    path('waiting-list', views.waiting_list, name = "waiting"),
    path('admin-dashboard', views.my_admin, name = "admin-dashboard"),
    path('reset_password/', auth_views.PasswordResetView.as_view(template_name="users/password_reset.html"), name = "reset_password"),
    path('reset_password_sent/', auth_views.PasswordResetDoneView.as_view(template_name="users/password_reset_sent.html"), name = "password_reset_done"),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name="users/password_reset_form.html"), name = "password_reset_confirm"),
    path('reset_password_complete/', auth_views.PasswordResetCompleteView.as_view(template_name="users/password_reset_done.html"), name = "password_reset_complete"),
    # password reset without sending email
    path("reset-password/", views.custom_password_reset, name="custom_password_reset"),
   
    
]