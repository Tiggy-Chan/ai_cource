import csv
from django.core.management.base import BaseCommand
from knowledge_graph.models import KnowledgeItem # 确保你的 app 名称和模型名称正确

class Command(BaseCommand):
    help = 'Imports knowledge data from a CSV file into the KnowledgeItem model'

    def add_arguments(self, parser):
        parser.add_argument('csv_file_path', type=str, help='The path to the CSV file to import.')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file_path']
        self.stdout.write(self.style.SUCCESS(f'Starting import from {csv_file_path}'))

        # Step 1: Create all KnowledgeItem instances without relationships first
        # This is a simplified approach. You'll need more sophisticated logic
        # to handle the hierarchical nature of your CSV and determine the true 'name' and 'parent'.
        
        created_items_map = {} # To quickly find items by name for relationship linking

        with open(csv_file_path, mode='r', encoding='utf-8-sig') as file: # utf-8-sig handles BOM
            reader = csv.reader(file)
            header = next(reader) # Skip header row

            current_parent_stack = [None] * 7 # For handling hierarchy in "节点名称" columns

            for row_num, row in enumerate(reader):
                if not any(row): # Skip empty rows
                    continue
                
                try:
                    node_type = row[0].strip()
                    # Columns for "节点名称" are from index 1 to 7 (7 columns)
                    node_name_cols = [name.strip() for name in row[1:8]] 
                    
                    predecessor_str = row[8].strip()
                    successor_str = row[9].strip()
                    related_str = row[10].strip()
                    tag_str = row[11].strip()
                    knowledge_point_category = row[12].strip()
                    node_description = row[13].strip()

                    # Determine the actual name and parent
                    item_name = ""
                    item_content = node_description # Default content
                    parent_item = None
                    
                    # Logic to extract hierarchical name and content:
                    # The rightmost non-empty "节点名称" column is usually the item's specific name.
                    # Content for "知识点" might be in these columns or in "节点说明".
                    
                    current_level = -1
                    for i in range(6, -1, -1): # Check from NodeName7 down to NodeName1
                        if node_name_cols[i]:
                            item_name = node_name_cols[i]
                            current_level = i
                            if node_type == "知识点" and not node_description: # If description is empty, use this as content
                                item_content = item_name
                            break
                    
                    if not item_name: # If all NodeName1-7 are empty, maybe use description or skip
                        self.stdout.write(self.style.WARNING(f"Row {row_num+2}: Could not determine item name. Skipping."))
                        continue

                    # Determine parent from the stack
                    if current_level > 0:
                        parent_name_candidate = current_parent_stack[current_level -1]
                        if parent_name_candidate and parent_name_candidate in created_items_map:
                           parent_item = created_items_map[parent_name_candidate]
                    
                    # Update parent stack for subsequent items at deeper or same level
                    if node_type == "分类":
                        for i in range(current_level, 7) :
                            current_parent_stack[i] = item_name if i == current_level else None


                    # Create or update the item
                    # This logic needs to be robust against duplicate names if not unique
                    # For simplicity, we assume 'name' combined with 'parent' could be unique strategy for categories
                    # but model has 'name' as unique. This parsing needs care.
                    # Here, we assume 'item_name' derived will be unique for now.
                    
                    if item_name in created_items_map:
                        # Handle cases where item_name might not be unique yet
                        # For this example, we'll skip if name already processed, assuming unique names from CSV
                        # A better approach: use a combination of name and parent to define uniqueness or update existing.
                        self.stdout.write(self.style.WARNING(f"Row {row_num+2}: Item with name '{item_name}' already processed. Check for uniqueness logic. Skipping creation."))
                        instance = created_items_map[item_name] # get existing
                    else:
                        instance, created = KnowledgeItem.objects.get_or_create(
                            name=item_name, # This must be unique. The CSV parsing logic for name is critical
                            defaults={
                                'item_type': node_type,
                                'content': item_content,
                                'parent': parent_item,
                                'csv_predecessor_nodes_str': predecessor_str,
                                'csv_successor_nodes_str': successor_str,
                                'csv_related_nodes_str': related_str,
                                'tags_str': tag_str,
                                'csv_knowledge_point_category': knowledge_point_category,
                            }
                        )
                        if created:
                            created_items_map[instance.name] = instance
                            self.stdout.write(self.style.SUCCESS(f"Created: {instance}"))
                        else: # Name was unique but somehow get_or_create found it - should not happen with unique=True if not in map
                            self.stdout.write(self.style.WARNING(f"Row {row_num+2}: Item '{item_name}' already existed (unexpected)."))
                            created_items_map[instance.name] = instance # ensure it's in map


                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error processing row {row_num+2}: {row}. Error: {e}"))
        
        self.stdout.write(self.style.SUCCESS(f'Finished initial item creation. {len(created_items_map)} items processed/created.'))

        # Step 2: Link relationships
        self.stdout.write(self.style.SUCCESS('Starting relationship linking...'))
        for item_name_key, item_instance in created_items_map.items():
            # Link Predecessors
            if item_instance.csv_predecessor_nodes_str:
                pre_names = [name.strip() for name in item_instance.csv_predecessor_nodes_str.split(';') if name.strip()]
                for pre_name in pre_names:
                    if pre_name in created_items_map:
                        item_instance.predecessor_nodes.add(created_items_map[pre_name])
                    else:
                        self.stdout.write(self.style.WARNING(f"Predecessor node '{pre_name}' for '{item_instance.name}' not found."))
            
            # Link Successors
            if item_instance.csv_successor_nodes_str:
                suc_names = [name.strip() for name in item_instance.csv_successor_nodes_str.split(';') if name.strip()]
                for suc_name in suc_names:
                    if suc_name in created_items_map:
                        item_instance.successor_nodes.add(created_items_map[suc_name])
                    else:
                        self.stdout.write(self.style.WARNING(f"Successor node '{suc_name}' for '{item_instance.name}' not found."))

            # Link Related
            if item_instance.csv_related_nodes_str:
                rel_names = [name.strip() for name in item_instance.csv_related_nodes_str.split(';') if name.strip()]
                for rel_name in rel_names:
                    if rel_name in created_items_map:
                        item_instance.related_nodes.add(created_items_map[rel_name])
                    else:
                        self.stdout.write(self.style.WARNING(f"Related node '{rel_name}' for '{item_instance.name}' not found."))
            item_instance.save() # Save after adding M2M relations

        self.stdout.write(self.style.SUCCESS('Successfully imported all data and linked relationships.')) 