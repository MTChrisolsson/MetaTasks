from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import Organization


class SupportTag(models.Model):
    name = models.CharField(max_length=64, unique=True)
    color = models.CharField(max_length=7, default='#0EA5E9')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tags_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SupportTicket(models.Model):
    CATEGORY_CHOICES = [
        ('bug_report', 'Bug Report'),
        ('feature_request', 'Feature Request'),
        ('billing', 'Billing'),
        ('technical_support', 'Technical Support'),
        ('general', 'General'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('awaiting_customer', 'Awaiting Customer'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    ticket_id = models.CharField(max_length=32, unique=True, db_index=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='support_tickets')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_tickets_created',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets_assigned',
    )

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default='medium')

    sla_deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    tags = models.ManyToManyField('SupportTag', blank=True, related_name='tickets')
    customer_satisfaction_score = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    is_archived = models.BooleanField(default=False)
    is_internal = models.BooleanField(default=False)

    related_tickets = models.ManyToManyField(
        'self',
        through='TicketRelationship',
        symmetrical=False,
        related_name='related_to_tickets',
        blank=True,
    )

    attachment = models.FileField(upload_to='support/tickets/%Y/%m/', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', 'created_at']),
            models.Index(fields=['organization', 'priority']),
            models.Index(fields=['organization', 'assigned_to']),
            models.Index(fields=['organization', 'category']),
        ]

    def __str__(self):
        return f"{self.ticket_id}: {self.title}"

    def save(self, *args, **kwargs):
        old_status = None
        if self.pk:
            old_status = SupportTicket.objects.filter(pk=self.pk).values_list('status', flat=True).first()

        if not self.ticket_id:
            self.ticket_id = self._generate_ticket_id()

        if self.status == 'resolved' and self.resolved_at is None:
            self.resolved_at = timezone.now()

        if self.status == 'closed' and self.closed_at is None:
            self.closed_at = timezone.now()
            if self.resolved_at is None:
                self.resolved_at = self.closed_at

        if old_status and old_status != self.status:
            if self.status != 'resolved' and old_status == 'resolved':
                self.resolved_at = None
            if self.status != 'closed' and old_status == 'closed':
                self.closed_at = None

        super().save(*args, **kwargs)

    def _generate_ticket_id(self):
        prefix = getattr(settings, 'CUSTOMER_SUPPORT', {}).get('TICKET_ID_PREFIX', 'TKT')
        last_ticket = SupportTicket.objects.filter(ticket_id__startswith=f'{prefix}-').order_by('-created_at').first()
        if not last_ticket:
            return f'{prefix}-00001'

        try:
            last_number = int(last_ticket.ticket_id.split('-')[-1])
        except (ValueError, IndexError):
            last_number = SupportTicket.objects.count()
        return f'{prefix}-{last_number + 1:05d}'


class TicketRelationship(models.Model):
    RELATIONSHIP_CHOICES = [
        ('duplicate', 'Duplicate'),
        ('related', 'Related'),
        ('depends_on', 'Depends On'),
    ]

    from_ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='relationships_from')
    to_ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='relationships_to')
    relationship_type = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES, default='related')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['from_ticket', 'to_ticket', 'relationship_type']
        indexes = [models.Index(fields=['from_ticket', 'to_ticket'])]


class SupportTicketComment(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_ticket_comments')
    comment_text = models.TextField()
    is_internal = models.BooleanField(default=False)
    attachment = models.FileField(upload_to='support/comments/%Y/%m/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['ticket', 'created_at']),
            models.Index(fields=['author', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            self.is_edited = True
        super().save(*args, **kwargs)


class SupportTemplate(models.Model):
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=32, choices=SupportTicket.CATEGORY_CHOICES)
    title_template = models.CharField(max_length=255)
    description_template = models.TextField()
    default_priority = models.CharField(max_length=16, choices=SupportTicket.PRIORITY_CHOICES, default='medium')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_templates_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ['name', 'category']

    def __str__(self):
        return self.name


class SupportTicketAuditLog(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=100)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_ticket_actions',
    )
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['ticket', 'timestamp'])]


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KBCategory(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='kb_categories',
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default='fa-book', blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name']
        unique_together = ['organization', 'slug']
        verbose_name = 'KB Category'
        verbose_name_plural = 'KB Categories'

    def __str__(self):
        return self.name


class KBArticle(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='kb_articles',
    )
    category = models.ForeignKey(
        KBCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articles',
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    content = models.TextField()
    excerpt = models.CharField(max_length=300, blank=True, help_text='Short summary shown in listings')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_public = models.BooleanField(
        default=True,
        help_text='Visible to customers; when False only staff can see it',
    )
    view_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)

    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='kb_articles_authored',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    # Ticket linkage — staff can mark a ticket as resolved-by-article
    related_tickets = models.ManyToManyField(
        SupportTicket,
        blank=True,
        related_name='kb_articles',
    )

    class Meta:
        ordering = ['-published_at', '-created_at']
        unique_together = ['organization', 'slug']
        indexes = [
            models.Index(fields=['organization', 'status', 'is_public']),
            models.Index(fields=['organization', 'category']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def helpfulness_ratio(self):
        total = self.helpful_count + self.not_helpful_count
        if total == 0:
            return None
        return round(self.helpful_count / total * 100)

