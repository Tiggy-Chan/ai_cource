from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm
from .models import StudyNote, KnowledgeItem
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from taggit.forms import TagField

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'first_name': '名字',
            'last_name': '姓氏',
            'email': '电子邮箱',
        }

class PasswordChangeForm(DjangoPasswordChangeForm):
    old_password = forms.CharField(
        label="旧密码",
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'autofocus': True, 'class': 'form-control'}),
    )
    new_password1 = forms.CharField(
        label="新密码",
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'form-control'}),
    )
    new_password2 = forms.CharField(
        label="确认新密码",
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].help_text = None # 移除默认的帮助文本

        # self.fields['new_password1'].help_text = '你的密码不能太简单。'
        # self.fields['new_password2'].help_text = '请再次输入新密码以确认。'

class StudyNoteForm(forms.ModelForm):
    related_knowledge_item = forms.ModelChoiceField(
        queryset=KnowledgeItem.objects.all(),
        required=False,
        label="关联知识点",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    class Meta:
        model = StudyNote
        fields = ['title', 'content', 'related_knowledge_item', 'tags', 'is_public']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': CKEditorUploadingWidget(),
            'is_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'title': '笔记标题',
            'content': '笔记内容',
            'tags': '标签 (用逗号分隔)',
            'is_public': '将此笔记设为公开',
        }
        help_texts = {
            'tags': '请输入标签，并用英文逗号或空格分隔。'
        }

    # 如果你想让标签字段在表单中不是必需的，可以这样做：
    # tags = TagField(required=False) 