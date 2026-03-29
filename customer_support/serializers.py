from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import KBArticle, KBCategory, SupportTicket, SupportTicketComment


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


class SupportTicketUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ['status', 'priority', 'assigned_to', 'severity', 'is_internal', 'is_archived']


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

