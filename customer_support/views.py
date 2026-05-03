from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from django.contrib import messages
from core.models import Organization
from licensing.models import License, Service
from licensing.views import license_dashboard as licensing_license_dashboard, organization_licenses as licensing_organization_licenses
from accounts.models import CustomUser
from .models import SupportTicket, KBCategory, SupportTicketComment
from .forms import SupportTicketForm, SupportTicketCommentForm, SupportTicketUpdateForm, SupportSearchForm

def is_support_staff(user):
    return user.is_superuser or (hasattr(user, 'mediap_profile') and user.mediap_profile.has_staff_panel_access)

@login_required
@user_passes_test(is_support_staff)
def portal_dashboard(request):
    """Central command center for platform-wide support"""
    
    ticket_stats = SupportTicket.objects.aggregate(
        open_count=Count('id', filter=Q(status='open')),
        in_progress_count=Count('id', filter=Q(status='in_progress')),
        awaiting_customer_count=Count('id', filter=Q(status='awaiting_customer')),
        resolved_today=Count('id', filter=Q(status='resolved', updated_at__date=timezone.now().date()))
    )

    context = {
        'total_accounts': CustomUser.objects.count(),
        'active_accounts': CustomUser.objects.filter(is_active=True).count(),
        'inactive_accounts': CustomUser.objects.filter(is_active=False).count(),
        'recent_activity_count': 0,  # Placeholder for audit logs
        'open_ticket_count': ticket_stats['open_count'],
        'in_progress_ticket_count': ticket_stats['in_progress_count'],
        'awaiting_customer_count': ticket_stats['awaiting_customer_count'],
        'recent_tickets': SupportTicket.objects.select_related('organization', 'created_by').order_by('-created_at')[:10],
        'kb_categories': KBCategory.objects.all().order_by('sort_order'),
    }
    return render(request, 'customer_support/dashboard.html', context)

@login_required
@user_passes_test(is_support_staff)
def organization_360_view(request, org_id):
    """A comprehensive view of an organization's state for support troubleshooting"""
    org = get_object_or_404(Organization, id=org_id)
    
    # Aggregate all relevant data for the support agent
    licenses = License.objects.filter(organization=org).select_related('license_type__service')
    members = org.members.select_related('user').all()
    tickets = SupportTicket.objects.filter(organization=org).order_by('-created_at')
    
    context = {
        'organization': org,
        'licenses': licenses,
        'members': members,
        'tickets': tickets,
        'stats': {
            'active_members': members.filter(is_active=True).count(),
            'total_tickets': tickets.count(),
        }
    }
    return render(request, 'customer_support/org_360.html', context)


@login_required
@user_passes_test(is_support_staff)
def support_licensing_dashboard(request):
    """
    Delegates to the main licensing dashboard view, ensuring support staff access.
    """
    return licensing_license_dashboard(request)


@login_required
@user_passes_test(is_support_staff)
def support_licensing_organization_detail(request, org_id):
    """Delegates to the organization-specific licensing view, ensuring support staff access."""
    return licensing_organization_licenses(request, org_id=org_id)


@login_required
@user_passes_test(is_support_staff)
def ticket_dashboard(request):
    """Dashboard for managing support tickets"""
    context = {
        'ticket_stats': SupportTicket.objects.aggregate(
            open_count=Count('id', filter=Q(status='open')),
            in_progress_count=Count('id', filter=Q(status='in_progress')),
            resolved_today=Count('id', filter=Q(status='resolved', updated_at__date=timezone.now().date()))
        ),
        'recent_tickets': SupportTicket.objects.select_related('organization', 'created_by').order_by('-created_at')[:10],
        'kb_categories': KBCategory.objects.all().order_by('sort_order'), # Potentially useful for ticket context
    }
    return render(request, 'customer_support/ticket_dashboard.html', context)

@login_required
@user_passes_test(is_support_staff)
def ticket_list(request):
    """Main list view for support tickets with filtering"""
    search_form = SupportSearchForm(request.GET)
    tickets_qs = SupportTicket.objects.select_related('organization', 'created_by', 'assigned_to').all()

    if search_form.is_valid():
        q = search_form.cleaned_data.get('search_query')
        if q:
            tickets_qs = tickets_qs.filter(Q(title__icontains=q) | Q(ticket_id__icontains=q))
        
        status = search_form.cleaned_data.get('status_filter')
        if status:
            tickets_qs = tickets_qs.filter(status=status)

    paginator = Paginator(tickets_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, 'customer_support/ticket_list.html', {
        'page_obj': page_obj,
        'search_form': search_form
    })

@login_required
@user_passes_test(is_support_staff)
def ticket_detail(request, ticket_id):
    """Detailed view for a specific ticket including comment history"""
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)
    comments = ticket.comments.select_related('author').all()
    comment_form = SupportTicketCommentForm()
    update_form = SupportTicketUpdateForm(instance=ticket, organization=ticket.organization)

    return render(request, 'customer_support/ticket_detail.html', {
        'ticket': ticket,
        'comments': comments,
        'comment_form': comment_form,
        'update_form': update_form,
    })

@login_required
@user_passes_test(is_support_staff)
def ticket_create(request):
    """View to manually create a ticket from the admin side"""
    if request.method == 'POST':
        form = SupportTicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            # Note: You'll need to handle organization selection in the form or view logic
            ticket.created_by = request.user
            ticket.save()
            messages.success(request, f"Ticket {ticket.ticket_id} created.")
            return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)
    else:
        form = SupportTicketForm()
    return render(request, 'customer_support/ticket_form.html', {'form': form})

@login_required
@user_passes_test(is_support_staff)
def ticket_add_comment(request, ticket_id):
    """Action view for adding comments to a ticket"""
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)
    if request.method == 'POST':
        form = SupportTicketCommentForm(request.POST, request.FILES)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.ticket = ticket
            comment.author = request.user
            comment.save()
            messages.success(request, "Comment added.")
    return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)

# Placeholder views to resolve remaining AttributeError crashes
@login_required
@user_passes_test(is_support_staff)
def ticket_update(request, ticket_id): return redirect('customer_support:ticket_detail', ticket_id=ticket_id)

@login_required
@user_passes_test(is_support_staff)
def ticket_close(request, ticket_id):
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)
    ticket.status = 'closed'
    ticket.save()
    messages.info(request, f"Ticket {ticket_id} closed.")
    return redirect('customer_support:ticket_detail', ticket_id=ticket_id)

@login_required
@user_passes_test(is_support_staff)
def ticket_merge(request, ticket_id): return redirect('customer_support:ticket_detail', ticket_id=ticket_id)

@login_required
@user_passes_test(is_support_staff)
def ticket_export(request, ticket_id): return redirect('customer_support:ticket_detail', ticket_id=ticket_id)

@login_required
@user_passes_test(is_support_staff)
def support_analytics(request): return render(request, 'customer_support/placeholder.html')

@login_required
@user_passes_test(is_support_staff)
def team_performance(request): return render(request, 'customer_support/placeholder.html')

@login_required
@user_passes_test(is_support_staff)
def ticket_trends(request): return render(request, 'customer_support/placeholder.html')

@login_required
@user_passes_test(is_support_staff)
def account_management(request):
    from core.models import UserProfile
    accounts = UserProfile.objects.all().select_related('user', 'organization')
    organizations = Organization.objects.all()
    return render(request, 'customer_support/account_management.html', {
        'accounts': accounts,
        'organizations': organizations
    })

@login_required
@user_passes_test(is_support_staff)
def account_detail(request, user_id):
    from core.models import UserProfile
    user_profile = get_object_or_404(UserProfile, id=user_id)
    return render(request, 'customer_support/account_detail.html', {'user_profile': user_profile})

@login_required
@user_passes_test(is_support_staff)
def toggle_account_status(request, user_id): return redirect('customer_support:account_management')

@login_required
@user_passes_test(is_support_staff)
def kb_list(request): return render(request, 'customer_support/placeholder.html')

@login_required
@user_passes_test(is_support_staff)
def kb_article_create(request): return redirect('customer_support:kb_list')

@login_required
@user_passes_test(is_support_staff)
def kb_article_detail(request, slug): return render(request, 'customer_support/placeholder.html')

@login_required
@user_passes_test(is_support_staff)
def kb_article_edit(request, slug): return redirect('customer_support:kb_list')

@login_required
def kb_article_helpful(request, slug): return redirect('customer_support:kb_list')

@login_required
def customer_portal_home(request): return render(request, 'customer_support/portal_home.html')

@login_required
def customer_my_tickets(request): return render(request, 'customer_support/portal_tickets.html')

@login_required
def customer_ticket_create(request): return render(request, 'customer_support/portal_ticket_form.html')

@login_required
def customer_ticket_detail(request, ticket_id): return render(request, 'customer_support/portal_ticket_detail.html')