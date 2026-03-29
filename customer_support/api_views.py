import csv

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    KBArticle,
    KBCategory,
    SupportTag,
    SupportTemplate,
    SupportTicket,
    SupportTicketAuditLog,
    SupportTicketComment,
    TicketRelationship,
)
from .serializers import (
    KBArticleDetailSerializer,
    KBArticleListSerializer,
    KBCategorySerializer,
    SupportTagSerializer,
    SupportTemplateSerializer,
    SupportTicketAuditLogSerializer,
    SupportTicketCommentSerializer,
    SupportTicketCreateSerializer,
    SupportTicketSerializer,
    SupportTicketUpdateSerializer,
    TicketRelationshipSerializer,
)


def get_user_support_tier(user):
    if not user.is_authenticated:
        return 'none'
    if user.is_superuser:
        return 'superuser'
    if user.is_staff or user.groups.filter(name='support_admin').exists():
        return 'staff'
    if user.groups.filter(name='support_agent').exists() or user.groups.filter(name='customer_support').exists():
        return 'support_agent'
    if hasattr(user, 'mediap_profile'):
        return 'customer'
    return 'none'


def get_ticket_queryset_for_user(user):
    profile = getattr(user, 'mediap_profile', None)
    queryset = SupportTicket.objects.select_related('organization', 'created_by', 'assigned_to').prefetch_related('tags')
    if profile:
        return queryset.filter(organization=profile.organization, is_archived=False)
    return queryset.none()


def log_ticket_audit(ticket, action, user, old_value=None, new_value=None):
    SupportTicketAuditLog.objects.create(
        ticket=ticket,
        action=action,
        performed_by=user,
        old_value=old_value or {},
        new_value=new_value or {},
    )


class SupportAccessPermission(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return get_user_support_tier(request.user) in {'superuser', 'staff', 'support_agent'}


class SupportStaffPermission(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return get_user_support_tier(request.user) in {'superuser', 'staff', 'support_agent'}


class SupportAdminPermission(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return get_user_support_tier(request.user) in {'superuser', 'staff'}


class SupportTicketViewSet(viewsets.ModelViewSet):
    permission_classes = [SupportAccessPermission]
    lookup_field = 'ticket_id'

    def get_permissions(self):
        if self.action in {'update', 'partial_update', 'destroy', 'status', 'assign'}:
            permission_classes = [SupportStaffPermission]
        else:
            permission_classes = [SupportAccessPermission]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        queryset = get_ticket_queryset_for_user(self.request.user)

        search = (self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(ticket_id__icontains=search)
                | Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(created_by__username__icontains=search)
                | Q(assigned_to__username__icontains=search)
            )

        status_filter = (self.request.query_params.get('status') or '').strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        priority_filter = (self.request.query_params.get('priority') or '').strip()
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)

        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return SupportTicketCreateSerializer
        if self.action in {'update', 'partial_update'}:
            return SupportTicketUpdateSerializer
        return SupportTicketSerializer

    def perform_create(self, serializer):
        ticket = serializer.save()
        log_ticket_audit(ticket, 'create', self.request.user, old_value={}, new_value={'status': ticket.status})

    def perform_update(self, serializer):
        old_ticket = self.get_object()
        old_value = {
            'status': old_ticket.status,
            'priority': old_ticket.priority,
            'assigned_to': old_ticket.assigned_to_id,
            'severity': old_ticket.severity,
            'is_internal': old_ticket.is_internal,
            'is_archived': old_ticket.is_archived,
        }
        ticket = serializer.save()
        new_value = {
            'status': ticket.status,
            'priority': ticket.priority,
            'assigned_to': ticket.assigned_to_id,
            'severity': ticket.severity,
            'is_internal': ticket.is_internal,
            'is_archived': ticket.is_archived,
        }
        log_ticket_audit(ticket, 'update', self.request.user, old_value=old_value, new_value=new_value)

    @action(detail=True, methods=['get', 'post'], permission_classes=[SupportAccessPermission])
    def comments(self, request, ticket_id=None):
        ticket = self.get_object()

        if request.method == 'GET':
            comments = SupportTicketComment.objects.filter(ticket=ticket).select_related('author').order_by('created_at')
            if get_user_support_tier(request.user) == 'customer':
                comments = comments.filter(is_internal=False)
            serializer = SupportTicketCommentSerializer(comments, many=True)
            return Response(serializer.data)

        serializer = SupportTicketCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(ticket=ticket, author=request.user)
        if get_user_support_tier(request.user) == 'customer':
            comment.is_internal = False
            comment.save(update_fields=['is_internal', 'updated_at'])
        log_ticket_audit(ticket, 'comment_added', request.user, old_value={}, new_value={'comment_id': comment.id})
        return Response(SupportTicketCommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'], permission_classes=[SupportStaffPermission])
    def status(self, request, ticket_id=None):
        ticket = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(SupportTicket.STATUS_CHOICES):
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)

        old_status = ticket.status
        ticket.status = new_status
        ticket.save(update_fields=['status', 'updated_at', 'resolved_at', 'closed_at'])
        log_ticket_audit(ticket, 'status_changed', request.user, old_value={'status': old_status}, new_value={'status': new_status})
        return Response(SupportTicketSerializer(ticket).data)

    @action(detail=True, methods=['post'], permission_classes=[SupportStaffPermission])
    def assign(self, request, ticket_id=None):
        ticket = self.get_object()
        assignee_id = request.data.get('assigned_to')
        if not assignee_id:
            return Response({'detail': 'assigned_to is required.'}, status=status.HTTP_400_BAD_REQUEST)

        user_qs = ticket.organization.members.select_related('user').filter(user__id=assignee_id)
        assignee_profile = user_qs.first()
        if not assignee_profile:
            return Response({'detail': 'Assignee must belong to the same organization.'}, status=status.HTTP_400_BAD_REQUEST)

        old_assignee = ticket.assigned_to_id
        ticket.assigned_to = assignee_profile.user
        ticket.save(update_fields=['assigned_to', 'updated_at'])
        log_ticket_audit(
            ticket,
            'assigned',
            request.user,
            old_value={'assigned_to': old_assignee},
            new_value={'assigned_to': ticket.assigned_to_id},
        )
        return Response(SupportTicketSerializer(ticket).data)

    @action(detail=True, methods=['post'], permission_classes=[SupportAccessPermission])
    def close(self, request, ticket_id=None):
        ticket = self.get_object()
        old_status = ticket.status
        ticket.status = 'closed'
        score = request.data.get('customer_satisfaction_score')
        if score is not None:
            try:
                ticket.customer_satisfaction_score = int(score)
            except (TypeError, ValueError):
                return Response({'detail': 'Invalid customer_satisfaction_score.'}, status=status.HTTP_400_BAD_REQUEST)
        ticket.save()
        log_ticket_audit(ticket, 'close', request.user, old_value={'status': old_status}, new_value={'status': 'closed'})
        return Response(SupportTicketSerializer(ticket).data)


class SupportAnalyticsDashboardAPIView(APIView):
    permission_classes = [SupportStaffPermission]

    def get(self, request):
        tickets = get_ticket_queryset_for_user(request.user)
        return Response(
            {
                'total_tickets': tickets.count(),
                'open_tickets': tickets.filter(status='open').count(),
                'in_progress_tickets': tickets.filter(status='in_progress').count(),
                'awaiting_customer_tickets': tickets.filter(status='awaiting_customer').count(),
                'resolved_tickets': tickets.filter(status='resolved').count(),
                'closed_tickets': tickets.filter(status='closed').count(),
                'avg_csat': tickets.aggregate(avg=Avg('customer_satisfaction_score')).get('avg') or 0,
            }
        )


class SupportAnalyticsSLAAPIView(APIView):
    permission_classes = [SupportStaffPermission]

    def get(self, request):
        tickets = get_ticket_queryset_for_user(request.user)
        now = timezone.now()
        total = tickets.exclude(status__in=['closed', 'resolved']).count()
        breached_count = tickets.exclude(status__in=['closed', 'resolved']).filter(
            sla_deadline__isnull=False,
            sla_deadline__lt=now,
        ).count()
        compliance_rate = 100.0 if total == 0 else max(0.0, ((total - breached_count) / total) * 100)
        return Response(
            {
                'total_open_with_sla': total,
                'breached_count': breached_count,
                'compliance_rate': round(compliance_rate, 2),
            }
        )


class SupportAnalyticsTeamAPIView(APIView):
    permission_classes = [SupportStaffPermission]

    def get(self, request):
        tickets = get_ticket_queryset_for_user(request.user)
        rows = (
            tickets.exclude(assigned_to__isnull=True)
            .values('assigned_to__id', 'assigned_to__username')
            .annotate(total_assigned=Count('id'), resolved=Count('id', filter=Q(status='resolved')))
            .order_by('-total_assigned')
        )
        return Response(list(rows))


class SupportAnalyticsCSVExportAPIView(APIView):
    permission_classes = [SupportStaffPermission]

    def get(self, request):
        tickets = get_ticket_queryset_for_user(request.user)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="support_analytics.csv"'
        writer = csv.writer(response)
        writer.writerow(['date', 'total_tickets'])

        rows = (
            tickets.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(total=Count('id'))
            .order_by('day')
        )
        for row in rows:
            writer.writerow([row['day'], row['total']])
        return response


# ---------------------------------------------------------------------------
# Knowledge Base API
# ---------------------------------------------------------------------------

class KBArticleViewSet(viewsets.ModelViewSet):
    """
    CRUD for KB articles.  Read access is open to all authenticated portal users;
    write actions (create/update/destroy) require staff tier.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'publish'):
            return [SupportStaffPermission()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return KBArticleDetailSerializer
        return KBArticleListSerializer

    def get_queryset(self):
        profile = getattr(self.request.user, 'mediap_profile', None)
        if not profile:
            return KBArticle.objects.none()
        qs = KBArticle.objects.select_related('category', 'authored_by').filter(
            organization=profile.organization
        ).annotate()  # placeholder for future annotations

        # Non-staff only see published public articles
        from .views import get_user_support_tier
        tier = get_user_support_tier(self.request.user)
        if tier not in {'superuser', 'staff', 'support_agent'}:
            qs = qs.filter(status=KBArticle.STATUS_PUBLISHED, is_public=True)

        # Query filters
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q))
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__slug=category)
        article_status = self.request.query_params.get('status')
        if article_status:
            qs = qs.filter(status=article_status)
        return qs

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'mediap_profile', None)
        serializer.save(
            organization=profile.organization if profile else None,
            authored_by=self.request.user,
        )

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        article = self.get_object()
        if article.status == KBArticle.STATUS_PUBLISHED:
            return Response({'detail': 'Article is already published.'}, status=status.HTTP_400_BAD_REQUEST)
        article.status = KBArticle.STATUS_PUBLISHED
        article.save(update_fields=['status', 'published_at', 'updated_at'])
        return Response(KBArticleDetailSerializer(article).data)

    @action(detail=True, methods=['post'])
    def helpful(self, request, pk=None):
        article = self.get_object()
        is_helpful = bool(request.data.get('helpful', True))
        if is_helpful:
            KBArticle.objects.filter(pk=article.pk).update(helpful_count=article.helpful_count + 1)
        else:
            KBArticle.objects.filter(pk=article.pk).update(not_helpful_count=article.not_helpful_count + 1)
        return Response({'success': True})


class KBCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = KBCategorySerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [SupportStaffPermission()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        profile = getattr(self.request.user, 'mediap_profile', None)
        if not profile:
            return KBCategory.objects.none()
        return KBCategory.objects.filter(organization=profile.organization).annotate(
            article_count=Count('articles')
        )

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'mediap_profile', None)
        serializer.save(organization=profile.organization if profile else None)


class SupportTagViewSet(viewsets.ModelViewSet):
    permission_classes = [SupportAccessPermission]
    serializer_class = SupportTagSerializer

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [SupportStaffPermission()]
        return [SupportAccessPermission()]

    def get_queryset(self):
        return SupportTag.objects.select_related('created_by').order_by('name')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SupportTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [SupportAccessPermission]
    serializer_class = SupportTemplateSerializer

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [SupportStaffPermission()]
        return [SupportAccessPermission()]

    def get_queryset(self):
        return SupportTemplate.objects.select_related('created_by').order_by('name')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TicketRelationshipViewSet(viewsets.ModelViewSet):
    permission_classes = [SupportStaffPermission]
    serializer_class = TicketRelationshipSerializer

    def get_queryset(self):
        profile = getattr(self.request.user, 'mediap_profile', None)
        if not profile:
            return TicketRelationship.objects.none()
        return TicketRelationship.objects.select_related(
            'from_ticket',
            'to_ticket',
            'created_by',
        ).filter(from_ticket__organization=profile.organization)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SupportTicketAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SupportStaffPermission]
    serializer_class = SupportTicketAuditLogSerializer

    def get_queryset(self):
        profile = getattr(self.request.user, 'mediap_profile', None)
        if not profile:
            return SupportTicketAuditLog.objects.none()

        queryset = SupportTicketAuditLog.objects.select_related('ticket', 'performed_by').filter(
            ticket__organization=profile.organization
        )

        ticket_id = (self.request.query_params.get('ticket_id') or '').strip()
        if ticket_id:
            queryset = queryset.filter(ticket__ticket_id=ticket_id)

        action_name = (self.request.query_params.get('action') or '').strip()
        if action_name:
            queryset = queryset.filter(action=action_name)

        return queryset

