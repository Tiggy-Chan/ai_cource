from django.contrib import admin
from .models import KnowledgeItem

@admin.register(KnowledgeItem)
class KnowledgeItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'item_type', 'parent', 'display_predecessors', 'display_successors', 'display_related_nodes')
    list_filter = ('item_type', 'parent')
    search_fields = ('name', 'content')
    autocomplete_fields = ['parent', 'predecessor_nodes', 'successor_nodes', 'related_nodes'] # 使得M2M字段更易于编辑
    
    fieldsets = (
        (None, {
            'fields': ('name', 'item_type', 'content', 'parent')
        }),
        ('CSV 原数据（参考）', {
            'classes': ('collapse',), # 默认折叠
            'fields': ('csv_predecessor_nodes_str', 'csv_successor_nodes_str', 'csv_related_nodes_str', 'tags_str', 'csv_knowledge_point_category'),
        }),
        ('节点关系 (编辑后生效)', {
            'fields': ('predecessor_nodes', 'successor_nodes', 'related_nodes'),
        }),
    )

    def display_predecessors(self, obj):
        return ", ".join([item.name for item in obj.predecessor_nodes.all()[:3]])
    display_predecessors.short_description = "前置节点 (部分)"

    def display_successors(self, obj):
        return ", ".join([item.name for item in obj.successor_nodes.all()[:3]])
    display_successors.short_description = "后置节点 (部分)"

    def display_related_nodes(self, obj):
        return ", ".join([item.name for item in obj.related_nodes.all()[:3]])
    display_related_nodes.short_description = "关联节点 (部分)"
