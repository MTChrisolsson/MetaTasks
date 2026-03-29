from django.contrib import admin

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


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('ticket_id', 'title', 'organization', 'status', 'priority', 'assigned_to', 'created_at')
    list_filter = ('status', 'priority', 'category', 'organization')
    search_fields = ('ticket_id', 'title', 'description')
    autocomplete_fields = ('created_by', 'assigned_to')


@admin.register(SupportTicketComment)
class SupportTicketCommentAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'author', 'is_internal', 'created_at', 'is_edited')
    list_filter = ('is_internal', 'is_edited')
    search_fields = ('ticket__ticket_id', 'comment_text')
    autocomplete_fields = ('ticket', 'author')


@admin.register(SupportTag)
class SupportTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'created_by', 'created_at')
    search_fields = ('name',)


@admin.register(SupportTemplate)
class SupportTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'default_priority', 'created_by', 'created_at')
    list_filter = ('category', 'default_priority')
    search_fields = ('name', 'title_template')


@admin.register(SupportTicketAuditLog)
class SupportTicketAuditLogAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'action', 'performed_by', 'timestamp')
    list_filter = ('action', 'timestamp')
    search_fields = ('ticket__ticket_id', 'action')


@admin.register(TicketRelationship)
class TicketRelationshipAdmin(admin.ModelAdmin):
    list_display = ('from_ticket', 'to_ticket', 'relationship_type', 'created_by', 'created_at')
    list_filter = ('relationship_type',)


@admin.register(KBCategory)
class KBCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'slug', 'sort_order', 'created_at')
    list_filter = ('organization',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(KBArticle)
class KBArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'category', 'status', 'is_public', 'view_count', 'authored_by', 'published_at')
    list_filter = ('status', 'is_public', 'organization', 'category')
    search_fields = ('title', 'content', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    autocomplete_fields = ('authored_by',)
