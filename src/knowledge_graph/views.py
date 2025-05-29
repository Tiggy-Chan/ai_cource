from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from .models import KnowledgeItem, StudyNote
from django.db.models import Q
import json
from django.http import JsonResponse, StreamingHttpResponse
from functools import reduce
import operator
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe
import re
from django.contrib import messages
from .forms import UserProfileForm, PasswordChangeForm, StudyNoteForm
from taggit.models import Tag
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings # 导入settings
import dashscope # 导入dashscope
from dashscope import Generation # 导入Generation
from http import HTTPStatus # 导入HTTPStatus

# Create your views here.

# 辅助函数：为节点定义样式 (可以根据需要扩展)
def get_node_style(item):
    if item.item_type == '分类':
        return {
            'group': 'category', # 用于vis.js的group属性
            'color': {'background':'#FFC107', 'border':'#FF9800', 'highlight': {'background':'#FFA000', 'border':'#FF6F00'}},
            'shape': 'box',
            'font': {'color': '#333333'}
        }
    elif item.item_type == '知识点':
        return {
            'group': 'knowledge_point',
            'color': {'background':'#4CAF50', 'border':'#388E3C', 'highlight': {'background':'#66BB6A', 'border':'#2E7D32'}},
            'shape': 'ellipse',
        }
    return {'group': 'default'} # 默认样式

# 辅助函数：将KnowledgeItem转换为vis.js节点格式
def format_node_for_vis(item, is_center=False):
    style = get_node_style(item)
    
    # Prepare detailed title for tooltip
    title_parts = [
        f"ID: {item.id}",
        f"类型: {item.get_item_type_display()}",
        f"名称: {item.name}"
    ]
    if item.parent:
        title_parts.append(f"父分类: {item.parent.name}")

    # Efficiently count children by type if the related manager is prefetched
    # This assumes 'children' is the related_name for the parent ForeignKey
    # If not prefetched, this will cause N+1 queries when formatting many nodes.
    # Ensure 'children' is in prefetch_related when querying KnowledgeItem for graph display.
    children_categories_count = 0
    children_knowledge_points_count = 0
    if hasattr(item, 'children') and item.children.exists(): # Check if children have been prefetched and exist
        for child in item.children.all(): # Iterate over prefetched children
            if child.item_type == '分类':
                children_categories_count += 1
            elif child.item_type == '知识点':
                children_knowledge_points_count += 1
    
    if children_categories_count > 0:
        title_parts.append(f"子分类数量: {children_categories_count}")
    if children_knowledge_points_count > 0:
        title_parts.append(f"子知识点数量: {children_knowledge_points_count}")
    
    # Predecessor/Successor/Related counts (optional, can be heavy if not prefetched)
    # For simplicity, we'll omit these direct counts in tooltip for now to avoid N+1 if not careful with prefetching
    # If you need them, ensure these M2M fields are also in prefetch_related.
    # title_parts.append(f"前置节点数: {item.predecessor_nodes.count()}") 
    # title_parts.append(f"后置节点数: {item.successor_nodes.count()}")

    content_summary = (item.content or "无内容")
    max_content_len = 150
    if len(content_summary) > max_content_len:
        content_summary = content_summary[:max_content_len] + "..."
    title_parts.append(f"内容: {content_summary}")

    node_title = "\\n".join(title_parts) # Use \n for newlines in Vis.js tooltip

    node_data = {
        'id': item.id,
        'label': item.name, # Label remains concise
        'title': node_title, # Detailed tooltip
        **style
    }
    if is_center:
        node_data['size'] = 30
        node_data['font'] = {'size': 18, 'color': style.get('font', {}).get('color', '#FFFFFF'), 'strokeWidth': 0, 'strokeColor': 'white'}
        node_data['fixed'] = False # 允许中心节点被物理引擎移动一点
        node_data['color'] = {'background':'#007bff', 'border':'#0056b3', 'highlight': {'background':'#0056b3', 'border':'#003f7f'}} # 中心节点特定颜色
        node_data['group'] = 'center_node'
    return node_data

# 辅助函数：添加节点和边到列表 (确保不重复添加节点)
def add_item_and_relations_to_graph(item, graph_nodes_map, graph_edges_list, is_center=False, source_item=None, edge_label="", edge_direction='to', relation_type_description=""):
    """
    Adds an item and its relation to the graph data.
    'item' is the target node of the relation.
    'source_item' is the source node of the relation.
    'relation_type_description' is a human-readable description for the edge tooltip.
    """
    if item.id not in graph_nodes_map:
        graph_nodes_map[item.id] = format_node_for_vis(item, is_center)

    if source_item and edge_label:
        edge_data = {
            'label': edge_label,
            'arrows': 'to',
            # Construct a more descriptive title for the edge tooltip
            'title': f"{source_item.name} --[{edge_label} ({relation_type_description})]--> {item.name}" if relation_type_description else f"{source_item.name} --[{edge_label}]--> {item.name}"
        }
        if edge_direction == 'to': # source_item -> item
            edge_data['from'] = source_item.id
            edge_data['to'] = item.id
            edge_data['title'] = f"{source_item.name} --[{edge_label} ({relation_type_description or '关联'})]--> {item.name}"

        else: # item -> source_item (edge direction is from item to source_item, but arrow points 'to' source_item)
            edge_data['from'] = item.id
            edge_data['to'] = source_item.id
            # Adjust title wording for 'from' direction if necessary, or keep it consistent
            # For "A is successor of B", the arrow is from B to A. Label: "是其前置". item=A, source_item=B
            # So, B --[是其前置 (前置关系)]--> A
            # For "A is predecessor of B", arrow is from A to B. Label "是其后继". item=B, source_item=A
            # So, A --[是其后继 (后继关系)]--> B
            edge_data['title'] = f"{item.name} --[{edge_label} ({relation_type_description or '关联'})]--> {source_item.name}"


        # Ensure unique edge ID if Vis.js requires it and you might add same 'from-to' with different labels/titles
        # For simplicity, we are not adding an explicit edge ID here, assuming from/to/label combination is distinct enough for display
        # or that Vis.js handles duplicate edges gracefully if they occur.
        # If explicit unique edge IDs are needed:
        # edge_data['id'] = f"edge_{source_item.id}_{item.id}_{edge_label.replace(' ', '_')}" # Example ID
        
        graph_edges_list.append(edge_data)

# Helper function for highlighting search terms
def highlight_terms(text, terms):
    if not text or not terms:
        return text
    
    # Sort terms by length, longest first, to handle overlapping terms correctly (e.g., "network" and "neural network")
    sorted_terms = sorted(terms, key=len, reverse=True)
    
    # Escape the text first to prevent XSS from original content
    highlighted_text = escape(text)
    
    for term in sorted_terms:
        if not term.strip(): # Skip empty terms
            continue
        # Escape the term for regex usage, then create case-insensitive regex
        # We want to highlight the original escaped text based on the term
        try:
            # Find all occurrences of the term (case-insensitive) in the original non-escaped text
            # to get their original casing for highlighting in the escaped text.
            # This is a bit complex due to escaping. A simpler approach is to just highlight the escaped term.

            # Simpler approach: highlight the escaped term within the already escaped text
            escaped_term = escape(term)
            # Use re.sub for case-insensitive replacement
            highlighted_text = re.sub(
                f'({re.escape(escaped_term)})',
                r'<mark>\1</mark>',
                highlighted_text,
                flags=re.IGNORECASE
            )
        except re.error: # In case of bad regex pattern from term
            pass # Skip highlighting for this term

    return mark_safe(highlighted_text)

# 新增的视图函数
@login_required
def knowledge_list_view(request):
    top_level_categories = KnowledgeItem.objects.filter(item_type='分类', parent__isnull=True).prefetch_related(
        'children'
    ).order_by('name')

    structured_knowledge = []
    for category in top_level_categories:
        category_data = {
            'id': category.id,
            'name': category.name,
            'content': category.content,
            'sub_items': []
        }
        children_items = category.children.all().order_by('item_type', 'name')
        
        for child in children_items:
            category_data['sub_items'].append({
                'id': child.id,
                'name': child.name,
                'item_type': child.get_item_type_display(),
                'content_summary': (child.content or '')[:100] + ('...' if len(child.content or '') > 100 else '')
            })
        structured_knowledge.append(category_data)
        
    context = {
        'structured_knowledge': structured_knowledge,
    }
    return render(request, 'knowledge_graph/knowledge_list.html', context)

# 首页视图
@login_required
def home(request):
    query = request.GET.get('q', '').strip()
    search_terms_list = [term for term in query.split() if term.strip()]

    search_results_qs = None
    answer_item = None
    answer_item_name_highlighted = None
    answer_item_content_highlighted = None
    related_public_notes = [] # 初始化为空列表
    matching_study_notes = [] # 新增：用于存放匹配的学习笔记
    
    graph_nodes_map = {} 
    graph_edges_list = [] # Initialize as empty list

    if query and search_terms_list:
        term_queries = []
        for term in search_terms_list:
            term_queries.append(Q(name__icontains=term) | Q(content__icontains=term))
        
        if term_queries:
            combined_query = reduce(operator.and_, term_queries)
            base_results_qs = KnowledgeItem.objects.filter(combined_query).select_related('parent').prefetch_related(
                'children', 'predecessor_nodes', 'successor_nodes', 'related_nodes'
            )

            if base_results_qs.exists():
                answer_item = base_results_qs.first() 
                
                answer_item_name_highlighted = highlight_terms(answer_item.name, search_terms_list)
                answer_item_content_highlighted = highlight_terms(answer_item.content, search_terms_list)

                # 获取关联的公开学习笔记
                related_public_notes = StudyNote.objects.filter(
                    related_knowledge_item=answer_item, 
                    is_public=True
                ).select_related('user').order_by('-updated_at')[:5] # 最多显示5条，按更新时间排序

                if answer_item:
                    # Populate graph_nodes_map and graph_edges_list
                    add_item_and_relations_to_graph(answer_item, graph_nodes_map, graph_edges_list, is_center=True, source_item=answer_item, relation_type_description="中心节点")
                    if answer_item.parent:
                        add_item_and_relations_to_graph(item=answer_item.parent, graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item, edge_label='属于分类', edge_direction='to', relation_type_description="父分类关系")
                    for child in answer_item.children.all()[:5]: 
                        add_item_and_relations_to_graph(item=child, graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item, edge_label='包含', edge_direction='to', relation_type_description=f"{child.get_item_type_display()}包含关系")
                    for pre_node in answer_item.predecessor_nodes.all()[:3]:
                         add_item_and_relations_to_graph(item=pre_node, graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item, edge_label='是其后继', edge_direction='to', relation_type_description="后继关系")
                    for suc_node in answer_item.successor_nodes.all()[:3]:
                        add_item_and_relations_to_graph(item=suc_node, graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item, edge_label='是其前置', edge_direction='to', relation_type_description="前置关系")
                    for rel_node in answer_item.related_nodes.all()[:3]:
                        is_duplicate = any((e['from'] == answer_item.id and e['to'] == rel_node.id and e['label'] == '相关') or (e['from'] == rel_node.id and e['to'] == answer_item.id and e['label'] == '相关') for e in graph_edges_list)
                        if not is_duplicate:
                            add_item_and_relations_to_graph(item=rel_node, graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item, edge_label='相关', edge_direction='to', relation_type_description="相互关联")
                
                search_results_qs = base_results_qs.order_by('name')
            else: 
                search_results_qs = KnowledgeItem.objects.none()

        # 新增：搜索学习笔记 (用户自己的笔记)
        study_note_term_queries = []
        for term in search_terms_list:
            study_note_term_queries.append(Q(title__icontains=term) | Q(content__icontains=term))
        
        if study_note_term_queries:
            combined_study_note_query = reduce(operator.and_, study_note_term_queries)
            matching_study_notes = StudyNote.objects.filter(
                user=request.user, # 只搜索当前用户的笔记
                is_public = True # 只搜索公开的笔记
            ).filter(combined_study_note_query).order_by('-updated_at')[:10] # 最多显示10条

    context = {
        'query': query,
        'answer_item': answer_item,
        'answer_item_name_highlighted': answer_item_name_highlighted,
        'answer_item_content_highlighted': answer_item_content_highlighted,
        'search_results': search_results_qs,
        'related_public_notes': related_public_notes,
        'matching_study_notes': matching_study_notes, # 新增到上下文
        # Ensure graph_nodes_json and graph_edges_json are always valid JSON strings
        'graph_nodes_json': json.dumps(list(graph_nodes_map.values()) if graph_nodes_map else []),
        'graph_edges_json': json.dumps(graph_edges_list if graph_edges_list else []),
    }
    return render(request, 'knowledge_graph/home.html', context)

# 登录视图
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # 登录成功后重定向到 LOGIN_REDIRECT_URL (在 settings.py 中设置的 '/')
            return redirect('home')
    else:
        form = AuthenticationForm()
    return render(request, 'knowledge_graph/login.html', {'form': form})

# 注册视图
def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # 注册成功后重定向到 LOGIN_REDIRECT_URL
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'knowledge_graph/register.html', {'form': form})

# 登出视图
def logout_view(request):
    logout(request)
    # 登出后重定向到 LOGOUT_REDIRECT_URL (在 settings.py 中设置的 '/')
    return redirect('home')

@login_required
def get_node_neighbors_api(request, node_id):
    try:
        center_node = KnowledgeItem.objects.select_related('parent').prefetch_related(
            'children', 'predecessor_nodes', 'successor_nodes', 'related_nodes'
        ).get(id=node_id)
    except KnowledgeItem.DoesNotExist:
        return JsonResponse({'nodes': [], 'edges': []}, status=404)

    graph_nodes_map = {}
    graph_edges_list = [] # 确保在此处初始化为空列表

    # 添加中心节点自身到nodes_map，但不作为is_center=True，因为我们只关心它的邻居
    # 并且确保它不会被重复添加到返回的节点列表中（下面 final_nodes 会处理）
    if center_node.id not in graph_nodes_map:
        graph_nodes_map[center_node.id] = format_node_for_vis(center_node, is_center=False)

    # --- 开始为所有关系类型添加边和相关节点 ---

    # Parent relationship
    if center_node.parent:
        add_item_and_relations_to_graph(
            item=center_node.parent, 
            graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list,
            source_item=center_node, 
            edge_label='属于分类', edge_direction='to', # 指向父节点
            relation_type_description="父分类关系"
        )
    
    # Children relationship
    for child in center_node.children.all(): # 获取所有子节点
        add_item_and_relations_to_graph(
            item=child,
            graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list,
            source_item=center_node,
            edge_label='包含', edge_direction='to', # 指向子节点
            relation_type_description=f"{child.get_item_type_display()}包含关系"
        )
    
    # Predecessor nodes (item is a predecessor OF center_node)
    #  pre_node ---[是其后继]--> center_node (edge from pre_node to center_node)
    #  In our function: item=pre_node, source_item=center_node, edge_label='是其后继', edge_direction='to' (source to item)
    #  This creates: center_node ---[是其后继]--> pre_node
    for pre_node in center_node.predecessor_nodes.all():
         add_item_and_relations_to_graph(
             item=pre_node,
             graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list,
             source_item=center_node, 
             edge_label='是其后继', edge_direction='to',
             relation_type_description="后继关系"
         )

    # Successor nodes (item is a successor OF center_node)
    #  center_node ---[是其前置]--> suc_node (edge from center_node to suc_node)
    #  In our function: item=suc_node, source_item=center_node, edge_label='是其前置', edge_direction='to'
    for suc_node in center_node.successor_nodes.all():
        add_item_and_relations_to_graph(
            item=suc_node,
            graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list,
            source_item=center_node,
            edge_label='是其前置', edge_direction='to',
            relation_type_description="前置关系"
        )
    
    # Related nodes
    for rel_node in center_node.related_nodes.all():
        # 避免重复添加对称的"相关"边 (如果已经从另一个方向添加了)
        is_duplicate = any(
            (e['from'] == center_node.id and e['to'] == rel_node.id and e['label'] == '相关') or \
            (e['from'] == rel_node.id and e['to'] == center_node.id and e['label'] == '相关')
            for e in graph_edges_list
        )
        if not is_duplicate:
            add_item_and_relations_to_graph(
                item=rel_node,
                graph_nodes_map=graph_nodes_map, graph_edges_list=graph_edges_list,
                source_item=center_node,
                edge_label='相关', edge_direction='to', # 保持箭头从中心节点指向相关节点
                relation_type_description="相互关联"
            )
    
    # 从 graph_nodes_map 中提取所有节点，但排除掉 center_node 本身，
    # 因为它应该已经在客户端的图谱中了。我们只发送新的邻居节点。
    final_nodes = [node for node_id, node in graph_nodes_map.items() if node_id != center_node.id]

    return JsonResponse({'nodes': final_nodes, 'edges': graph_edges_list})

# 新增 "关于" 页面视图
@login_required # 或者移除 @login_required 如果你希望未登录用户也能访问此页面
def about_view(request):
    # 这个视图很简单，只是渲染一个静态模板。
    # 如果需要，你可以在这里传递一些动态数据到模板的 context 中。
    return render(request, 'knowledge_graph/about.html')

# 新增 "用户个人中心" 页面视图
@login_required # 此页面必须登录才能访问
def profile_view(request):
    user = request.user
    profile_form = UserProfileForm(instance=user)
    password_form = PasswordChangeForm(user=user)

    if request.method == 'POST':
        if 'update_profile' in request.POST: # 检查是哪个表单提交了
            profile_form = UserProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, '你的资料已成功更新！')
                return redirect('profile') # 重定向回个人资料页面
            else:
                messages.error(request, '更新资料失败，请检查表单错误。')
        elif 'change_password' in request.POST:
            password_form = PasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)  # 更新会话，防止用户登出
                messages.success(request, '你的密码已成功修改！')
                return redirect('profile') # 重定向回个人资料页面
            else:
                messages.error(request, '修改密码失败，请检查表单错误。')

    context = {
        'current_user': user,
        'profile_form': profile_form,
        'password_form': password_form,
    }
    return render(request, 'knowledge_graph/profile.html', context)

# 学习笔记视图
@login_required
def study_note_list_view(request):
    notes_qs = StudyNote.objects.filter(user=request.user)
    page_title = "我的学习笔记"
    current_visibility_filter = request.GET.get('visibility', 'all')

    if current_visibility_filter == 'public':
        notes_qs = notes_qs.filter(is_public=True)
        page_title = "我的公开笔记"
    elif current_visibility_filter == 'private':
        notes_qs = notes_qs.filter(is_public=False)
        page_title = "我的私有笔记"

    ordered_notes = notes_qs.order_by('-updated_at')

    paginator = Paginator(ordered_notes, 10) # 每页显示 10 条笔记
    page_number = request.GET.get('page')
    try:
        notes_page = paginator.page(page_number)
    except PageNotAnInteger:
        notes_page = paginator.page(1)
    except EmptyPage:
        notes_page = paginator.page(paginator.num_pages)

    return render(request, 'knowledge_graph/study_note_list.html', {
        'notes_page': notes_page, # 注意这里从 'notes' 改为 'notes_page'
        'page_title': page_title,
        'current_visibility_filter': current_visibility_filter
    })

@login_required
def study_note_list_by_tag_view(request, tag_slug):
    tag = get_object_or_404(Tag, slug=tag_slug)
    notes_qs = StudyNote.objects.filter(user=request.user, tags__in=[tag])
    page_title = f'标签为 "{tag.name}" 的笔记'
    current_visibility_filter = request.GET.get('visibility', 'all')

    if current_visibility_filter == 'public':
        notes_qs = notes_qs.filter(is_public=True)
        page_title = f'标签为 "{tag.name}" 的公开笔记'
    elif current_visibility_filter == 'private':
        notes_qs = notes_qs.filter(is_public=False)
        page_title = f'标签为 "{tag.name}" 的私有笔记'

    ordered_notes = notes_qs.order_by('-updated_at')

    paginator = Paginator(ordered_notes, 10) # 每页显示 10 条笔记
    page_number = request.GET.get('page')
    try:
        notes_page = paginator.page(page_number)
    except PageNotAnInteger:
        notes_page = paginator.page(1)
    except EmptyPage:
        notes_page = paginator.page(paginator.num_pages)

    return render(request, 'knowledge_graph/study_note_list.html', {
        'notes_page': notes_page, # 注意这里从 'notes' 改为 'notes_page'
        'tag': tag, 
        'page_title': page_title,
        'current_visibility_filter': current_visibility_filter
    })

@login_required
def study_note_detail_view(request, pk):
    note = get_object_or_404(StudyNote, pk=pk, user=request.user)
    return render(request, 'knowledge_graph/study_note_detail.html', {'note': note})

@login_required
def study_note_create_view(request):
    if request.method == 'POST':
        form = StudyNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.user = request.user
            note.save()
            messages.success(request, '学习笔记已成功创建！')
            return redirect('study_note_list')
    else:
        form = StudyNoteForm()
    return render(request, 'knowledge_graph/study_note_form.html', {'form': form, 'action': '创建'})

@login_required
def study_note_update_view(request, pk):
    note = get_object_or_404(StudyNote, pk=pk, user=request.user)
    if request.method == 'POST':
        form = StudyNoteForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            messages.success(request, '学习笔记已成功更新！')
            return redirect('study_note_detail', pk=note.pk)
    else:
        form = StudyNoteForm(instance=note)
    return render(request, 'knowledge_graph/study_note_form.html', {'form': form, 'note': note, 'action': '编辑'})

@login_required
def study_note_delete_view(request, pk):
    note = get_object_or_404(StudyNote, pk=pk, user=request.user)
    if request.method == 'POST':
        note.delete()
        messages.success(request, '学习笔记已成功删除！')
        return redirect('study_note_list')
    return render(request, 'knowledge_graph/study_note_confirm_delete.html', {'note': note})

def public_note_view(request, share_slug):
    note = get_object_or_404(StudyNote, share_slug=share_slug, is_public=True)
    return render(request, 'knowledge_graph/public_note_detail.html', {'note': note})

@login_required
def qwen_chat_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            incoming_messages = data.get('messages')

            if not incoming_messages or not isinstance(incoming_messages, list) or not incoming_messages[-1]['content']:
                return JsonResponse({'error': 'Messages list not provided or invalid'}, status=400)

            current_user_query = incoming_messages[-1]['content']

            api_key = getattr(settings, 'DASHSCOPE_API_KEY', None)
            if not api_key:
                return JsonResponse({'error': 'API key not configured'}, status=500)
            dashscope.api_key = api_key

            related_notes_context_str = ""
            if request.user.is_authenticated:
                query_keywords = current_user_query.split()
                note_queries = [Q(title__icontains=kw) | Q(content__icontains=kw) for kw in query_keywords if kw]
                if note_queries:
                    combined_note_query = reduce(operator.or_, note_queries)
                    user_notes = StudyNote.objects.filter(user=request.user).filter(combined_note_query).order_by('-updated_at')[:2]
                    if user_notes:
                        notes_extracts = []
                        for note in user_notes:
                            title = strip_tags(note.title)
                            content_summary = strip_tags(note.content)[:200]
                            notes_extracts.append(f"笔记标题: {title}\\\\n内容摘要: {content_summary}")
                        if notes_extracts:
                            related_notes_context_str = "参考用户之前的相关笔记：\\\\n" + "\\\\n---\\\\n".join(notes_extracts) + "\\\\n---\\\\n"
            
            messages_for_api = []
            messages_for_api.append({
                'role': 'system', 
                'content': 'You are a helpful and knowledgeable assistant. When a user asks a question, if context from their previous notes is provided, please consider it to give a more personalized and relevant answer. Answer in Chinese.'
            })

            MAX_HISTORY_MESSAGES = 10
            history_to_include = incoming_messages[:-1]
            if len(history_to_include) > MAX_HISTORY_MESSAGES:
                history_to_include = history_to_include[-MAX_HISTORY_MESSAGES:]
            messages_for_api.extend(history_to_include)

            user_final_input_content = current_user_query
            if related_notes_context_str:
                user_final_input_content = related_notes_context_str + "基于以上笔记参考（如有）和你的问题，请回答：\\\\n" + current_user_query
            
            messages_for_api.append({'role': 'user', 'content': user_final_input_content})
            messages_for_api = [m for m in messages_for_api if m.get('content')]

            # Define the streaming generator function
            def stream_response_generator():
                response_generator = Generation.call(
                    model="qwen-turbo",
                    messages=messages_for_api,
                    result_format='message',
                    stream=True,  
                    incremental_output=True 
                )
                
                for response_chunk in response_generator:
                    # print(f"--- Backend Log: Raw response_chunk from Dashscope: {response_chunk}") 
                    if response_chunk.status_code == HTTPStatus.OK:
                        actual_content_piece = ""
                        sdk_finish_reason = None
                        
                        if response_chunk.output and response_chunk.output.choices:
                            message_choice = response_chunk.output.choices[0]
                            actual_content_piece = message_choice.message.content
                            sdk_finish_reason = message_choice.finish_reason 
                            # print(f"--- Backend Log: Extracted content_piece: '{actual_content_piece}', SDK finish_reason: '{sdk_finish_reason}'") 
                        else:
                            # print(f"--- Backend Log: Response OK, but no output.choices found in response_chunk: {response_chunk}")
                            pass # No content to send, but not an error in itself for the stream
                        
                        chunk_data = {'reply_piece': actual_content_piece}
                        
                        if sdk_finish_reason and isinstance(sdk_finish_reason, str) and sdk_finish_reason.lower() == "stop":
                            chunk_data['finish_reason'] = sdk_finish_reason
                            # print(f"--- Backend Log: Sending TERMINAL finish_reason to client: {sdk_finish_reason}")
                        
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                        
                        if chunk_data.get('finish_reason'):
                            break
                    else:
                        error_message = f"Qwen API error in stream: Request id: {response_chunk.request_id}, Status code: {response_chunk.status_code}, error code: {response_chunk.code}, error message: {response_chunk.message}"
                        # print(f"--- Backend Log: {error_message}")
                        yield f"data: {json.dumps({'error': error_message})}\n\n"
                        break 

            return StreamingHttpResponse(stream_response_generator(), content_type='text/event-stream')

        except json.JSONDecodeError:
            # This error is for the initial request body, not for stream chunks
            return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
        except Exception as e:
            print(f"Error in qwen_chat_view setup: {e}")
            # This error is for the initial request setup, not for stream chunks
            return JsonResponse({'error': f'An unexpected error occurred during setup: {str(e)}'}, status=500)
            
    return JsonResponse({'error': 'Only POST method is allowed'}, status=405)

@login_required # Or remove if public access to this API is desired and safe
def knowledge_base_search_api(request):
    query = request.GET.get('q', '').strip()
    search_terms_list = [term for term in query.split() if term.strip()]

    answer_item_data = None
    search_results_data = []
    graph_nodes_list = []
    graph_edges_list = []
    # matching_study_notes_data = [] # We can also include user's study notes related to the KB item if needed

    if query and search_terms_list:
        term_queries = []
        for term in search_terms_list:
            term_queries.append(Q(name__icontains=term) | Q(content__icontains=term))
        
        if term_queries:
            combined_query = reduce(operator.and_, term_queries)
            base_results_qs = KnowledgeItem.objects.filter(combined_query).select_related('parent').prefetch_related(
                'children', 'predecessor_nodes', 'successor_nodes', 'related_nodes'
            )

            if base_results_qs.exists():
                answer_item_obj = base_results_qs.first()
                
                answer_item_data = {
                    'id': answer_item_obj.id,
                    'name': answer_item_obj.name,
                    'content': answer_item_obj.content,
                    'item_type_display': answer_item_obj.get_item_type_display(),
                    'name_highlighted': highlight_terms(answer_item_obj.name, search_terms_list),
                    'content_highlighted': highlight_terms(answer_item_obj.content, search_terms_list)
                }
                
                # Graph data population
                temp_graph_nodes_map = {}
                # Pass answer_item_obj to add_item_and_relations_to_graph
                add_item_and_relations_to_graph(answer_item_obj, temp_graph_nodes_map, graph_edges_list, is_center=True, source_item=answer_item_obj, relation_type_description="中心节点")
                if answer_item_obj.parent:
                    add_item_and_relations_to_graph(item=answer_item_obj.parent, graph_nodes_map=temp_graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item_obj, edge_label='属于分类', edge_direction='to', relation_type_description="父分类关系")
                for child in answer_item_obj.children.all()[:5]: 
                    add_item_and_relations_to_graph(item=child, graph_nodes_map=temp_graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item_obj, edge_label='包含', edge_direction='to', relation_type_description=f"{child.get_item_type_display()}包含关系")
                for pre_node in answer_item_obj.predecessor_nodes.all()[:3]:
                     add_item_and_relations_to_graph(item=pre_node, graph_nodes_map=temp_graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item_obj, edge_label='是其后继', edge_direction='to', relation_type_description="后继关系")
                for suc_node in answer_item_obj.successor_nodes.all()[:3]:
                    add_item_and_relations_to_graph(item=suc_node, graph_nodes_map=temp_graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item_obj, edge_label='是其前置', edge_direction='to', relation_type_description="前置关系")
                for rel_node in answer_item_obj.related_nodes.all()[:3]:
                    is_duplicate_edge = any((e['from'] == answer_item_obj.id and e['to'] == rel_node.id and e['label'] == '相关') or \
                                          (e['from'] == rel_node.id and e['to'] == answer_item_obj.id and e['label'] == '相关') for e in graph_edges_list)
                    if not is_duplicate_edge:
                        add_item_and_relations_to_graph(item=rel_node, graph_nodes_map=temp_graph_nodes_map, graph_edges_list=graph_edges_list, source_item=answer_item_obj, edge_label='相关', edge_direction='to', relation_type_description="相互关联")
                
                graph_nodes_list = list(temp_graph_nodes_map.values())

                # Prepare search_results_data (other related items)
                for item in base_results_qs.order_by('name'):
                    if item.id != answer_item_obj.id:
                        search_results_data.append({
                            'id': item.id,
                            'name': item.name,
                            'item_type_display': item.get_item_type_display(),
                            'content_summary': (strip_tags(item.content)[:100] + '...' if item.content and len(strip_tags(item.content)) > 100 else strip_tags(item.content or '')),
                            'url_encoded_name': item.name # Front-end will need to urlencode this if it constructs links
                        })
            # else: # No KnowledgeItem found for the query
                # answer_item_data remains None, search_results_data remains empty
                # graph_nodes_list and graph_edges_list remain empty

    return JsonResponse({
        'query': query,
        'answer_item': answer_item_data,
        'search_results': search_results_data,
        'graph_nodes': graph_nodes_list, # Directly pass the list
        'graph_edges': graph_edges_list  # Directly pass the list
    })
