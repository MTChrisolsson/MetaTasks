from django.contrib.auth import get_user_model
from rest_framework import serializers

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


class SupportTicketCommentSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = SupportTicketComment
        fields = [
            'id',
            'ticket',
            'author',
            'author_username',
            'comment_text',
            'is_internal',
            'attachment',
            'created_at',
            'updated_at',
            'is_edited',
        ]
        read_only_fields = ['id', 'ticket', 'author', 'created_at', 'updated_at', 'is_edited']


class SupportTicketSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True)
    tags = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            'id',
            'ticket_id',
            'organization',
            'created_by',
            'created_by_username',
            'assigned_to',
            'assigned_to_username',
            'title',
            'description',
            'category',
            'priority',
            'status',
            'severity',
            'sla_deadline',
            'created_at',
            'updated_at',
            'resolved_at',
            'closed_at',
            'tags',
            'customer_satisfaction_score',
            'is_archived',
            'is_internal',
            'attachment',
        ]
        read_only_fields = [
            'id',
            'ticket_id',
            'organization',
            'created_by',
            'created_by_username',
            'assigned_to_username',
            'created_at',
            'updated_at',
            'resolved_at',
            'closed_at',
            'tags',
        ]

    def validate_assigned_to(self, value):
        if not value:
            return value
        request = self.context.get('request')
        profile = getattr(request.user, 'mediap_profile', None) if request else None
        if profile and not get_user_model().objects.filter(
            id=value.id,
            mediap_profile__organization=profile.organization,
        ).exists():
            raise serializers.ValidationError('Assigned user must belong to your organization.')
        return value


class SupportTicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ['title', 'description', 'category', 'priority', 'severity', 'attachment']

    def create(self, validated_data):
        request = self.context.get('request')
        profile = getattr(request.user, 'mediap_profile', None) if request else None
        if not profile:
            raise serializers.ValidationError({'detail': 'A valid organization profile is required.'})
        return SupportTicket.objects.create(
            organization=profile.organization,
            created_by=request.user,
            **validated_data,
        )


class SupportTicketUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ['status', 'priority', 'assigned_to', 'severity', 'is_internal', 'is_archived']


class SupportTagSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = SupportTag
        fields = ['id', 'name', 'color', 'created_by', 'created_by_username', 'created_at']
        read_only_fields = ['id', 'created_by', 'created_by_username', 'created_at']


class SupportTemplateSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = SupportTemplate
        fields = [
            'id',
            'name',
            'category',
            'title_template',
            'description_template',
            'default_priority',
            'created_by',
            'created_by_username',
            'created_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_by_username', 'created_at']


class TicketRelationshipSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = TicketRelationship
        fields = [
            'id',
            'from_ticket',
            'to_ticket',
            'relationship_type',
            'created_by',
            'created_by_username',
            'created_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_by_username', 'created_at']

    def validate(self, attrs):
        from_ticket = attrs.get('from_ticket')
        to_ticket = attrs.get('to_ticket')

        if from_ticket and to_ticket and from_ticket.organization_id != to_ticket.organization_id:
            raise serializers.ValidationError('Both tickets must belong to the same organization.')
        if from_ticket and to_ticket and from_ticket.id == to_ticket.id:
            raise serializers.ValidationError('A ticket cannot relate to itself.')

        request = self.context.get('request')
        profile = getattr(request.user, 'mediap_profile', None) if request else None
        if profile and from_ticket and from_ticket.organization_id != profile.organization_id:
            raise serializers.ValidationError('Tickets must belong to your organization.')

        return attrs


class SupportTicketAuditLogSerializer(serializers.ModelSerializer):
    performed_by_username = serializers.CharField(source='performed_by.username', read_only=True)
    ticket_id = serializers.CharField(source='ticket.ticket_id', read_only=True)

    class Meta:
        model = SupportTicketAuditLog
        fields = [
            'id',
            'ticket',
            'ticket_id',
            'action',
            'performed_by',
            'performed_by_username',
            'old_value',
            'new_value',
            'timestamp',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Knowledge Base serializers
# ---------------------------------------------------------------------------

class KBCategorySerializer(serializers.ModelSerializer):
    article_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = KBCategory
        fields = ['id', 'name', 'slug', 'description', 'icon', 'sort_order', 'article_count', 'created_at']
        read_only_fields = ['id', 'created_at']


class KBArticleListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    authored_by_username = serializers.CharField(source='authored_by.username', read_only=True)
    helpfulness_ratio = serializers.IntegerField(read_only=True)

    class Meta:
        model = KBArticle
        fields = [
            'id', 'title', 'slug', 'category', 'category_name', 'excerpt',
            'status', 'is_public', 'view_count', 'helpful_count',
            'not_helpful_count', 'helpfulness_ratio',
            'authored_by', 'authored_by_username',
            'created_at', 'updated_at', 'published_at',
        ]
        read_only_fields = ['id', 'view_count', 'helpful_count', 'not_helpful_count', 'created_at', 'updated_at']


class KBArticleDetailSerializer(KBArticleListSerializer):
    class Meta(KBArticleListSerializer.Meta):
        fields = KBArticleListSerializer.Meta.fields + ['content']

