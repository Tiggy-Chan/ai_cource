from django.db import models
from django.conf import settings
from taggit.managers import TaggableManager
import uuid

class KnowledgeItem(models.Model):
    ITEM_TYPES = [
        ('分类', '分类'),
        ('知识点', '知识点'),
    ]
    name = models.CharField(max_length=500, unique=True, verbose_name="名称/标题") # Ensure names are unique for easy lookup
    item_type = models.CharField(max_length=10, choices=ITEM_TYPES, verbose_name="条目类型")
    content = models.TextField(blank=True, null=True, verbose_name="内容/描述")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children', verbose_name="父级分类")
    # For fields from CSV that might have multiple values separated by semicolons
    csv_predecessor_nodes_str = models.TextField(blank=True, null=True, verbose_name="CSV前置节点原始字符串")
    csv_successor_nodes_str = models.TextField(blank=True, null=True, verbose_name="CSV后置节点原始字符串")
    csv_related_nodes_str = models.TextField(blank=True, null=True, verbose_name="CSV关联节点原始字符串")
    
    tags_str = models.CharField(max_length=500, blank=True, null=True, verbose_name="标签（CSV原始）")
    csv_knowledge_point_category = models.CharField(max_length=255, blank=True, null=True, verbose_name="知识点分类（CSV原始）")

    # ManyToManyFields for actual relationships after parsing the string fields
    predecessor_nodes = models.ManyToManyField('self', symmetrical=False, related_name='successor_of', blank=True, verbose_name="前置节点")
    successor_nodes = models.ManyToManyField('self', symmetrical=False, related_name='predecessor_of', blank=True, verbose_name="后置节点")
    related_nodes = models.ManyToManyField('self', symmetrical=True, blank=True, verbose_name="关联节点")


    def __str__(self):
        return f"{self.get_item_type_display()}: {self.name}"

    class Meta:
        verbose_name = "知识条目"
        verbose_name_plural = "知识条目"
        ordering = ['name']

# You might want a separate Tag model if tags are complex or frequently reused across items
# class Tag(models.Model):
#     name = models.CharField(max_length=100, unique=True)
#     def __str__(self):
#         return self.name
#
# KnowledgeItem would then have:
# tags = models.ManyToManyField(Tag, blank=True, verbose_name="标签")

class StudyNote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_notes', verbose_name="用户")
    title = models.CharField(max_length=255, verbose_name="笔记标题")
    content = models.TextField(verbose_name="笔记内容")
    related_knowledge_item = models.ForeignKey(KnowledgeItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='study_notes', verbose_name="关联知识点")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    tags = TaggableManager(blank=True, verbose_name="标签")
    is_public = models.BooleanField(default=False, verbose_name="是否公开")
    share_slug = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name="分享链接ID")

    def __str__(self):
        return f"{self.title} (用户: {self.user.username})"

    class Meta:
        verbose_name = "学习笔记"
        verbose_name_plural = "学习笔记"
        ordering = ['-updated_at']
