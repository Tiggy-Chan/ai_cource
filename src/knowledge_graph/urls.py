from django.urls import path
from . import views # 导入当前应用的视图

urlpatterns = [
    path('', views.home, name='home'), # 首页路由
    path('list/', views.knowledge_list_view, name='knowledge_list'), # 新增知识点列表页路由
    path('about/', views.about_view, name='about'),  # 新增 "关于" 页面路由
    path('profile/', views.profile_view, name='profile'), # 新增 "个人中心" 页面路由
    path('login/', views.login_view, name='login'), # 登录页路由
    path('register/', views.register_view, name='register'), # 注册页路由
    path('logout/', views.logout_view, name='logout'), # 登出路由
    path('api/node_neighbors/<int:node_id>/', views.get_node_neighbors_api, name='api_node_neighbors'), # 新增API路由

    # 学习笔记 URLs
    path('notes/', views.study_note_list_view, name='study_note_list'),
    path('notes/tag/<slug:tag_slug>/', views.study_note_list_by_tag_view, name='study_note_list_by_tag'), # 新增按标签筛选
    path('notes/create/', views.study_note_create_view, name='study_note_create'),
    path('notes/<int:pk>/', views.study_note_detail_view, name='study_note_detail'),
    path('notes/<int:pk>/update/', views.study_note_update_view, name='study_note_update'),
    path('notes/<int:pk>/delete/', views.study_note_delete_view, name='study_note_delete'),
    path('note/public/<uuid:share_slug>/', views.public_note_view, name='public_note_detail'), # 公开笔记的查看链接

    # 通义千问聊天 API
    path('api/qwen_chat/', views.qwen_chat_view, name='qwen_chat_api'),

    # 新增：知识库搜索 API
    path('api/kb_search/', views.knowledge_base_search_api, name='knowledge_base_search_api'),
] 