from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from . import views

app_name = 'accounts'

urlpatterns = [
    # Registration flow - starts with account type selection
    path('register/', views.AccountTypeSelectionView.as_view(), name='register'),
    path('register/personal/', views.PersonalRegistrationView.as_view(), name='personal_register'),
    path('register/business/', views.BusinessRegistrationView.as_view(), name='business_register'),
    path('register/organization/', views.OrganizationCreationView.as_view(), name='create_organization'),
    path('register/invite-members/', views.InviteMembersView.as_view(), name='invite_members'),
    
    # Upgrade path
    path('upgrade-to-business/', views.upgrade_to_business, name='upgrade_to_business'),
    
    # Authentication
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            email_template_name='accounts/password_reset_email.txt',
            subject_template_name='accounts/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html'
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html'
        ),
        name='password_reset_complete',
    ),
    path('profile/', views.profile_view, name='profile'),
    path('profile/setup/', views.ProfileSetupView.as_view(), name='profile_setup'),
]
