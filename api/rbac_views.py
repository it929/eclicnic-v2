from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Count
from users.models import Role, SystemModule, SubModule, RolePermission, Category, User
from users.rbac_seed import seed_rbac


class RoleListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        roles = Role.objects.all().order_by('name')
        data = []
        for r in roles:
            user_count = User.objects.filter(role=r).count()
            if user_count == 0 and r.category:
                user_count = User.objects.filter(department=r.category).count()
            
            perms = RolePermission.objects.filter(role=r).select_related('module').prefetch_related('submodules').order_by('module__order', 'module__id')
            modules_count = perms.count()
            submodules_count = sum(p.submodules.count() for p in perms)

            modules_data = []
            for p in perms:
                mod = p.module
                subs = [
                    {
                        'id': s.id,
                        'name': s.name,
                        'code': s.code,
                        'route': s.route or '',
                        'icon': s.icon or 'fa-circle',
                        'tab_key': s.tab_key or '',
                        'sub_tab': s.sub_tab or '',
                        'sub_sub_tab': s.sub_sub_tab or '',
                        'description': s.description or '',
                        'order': s.order,
                    }
                    for s in p.submodules.filter(is_active=True).order_by('order', 'id')
                ]
                modules_data.append({
                    'id': mod.id,
                    'name': mod.name,
                    'code': mod.code,
                    'icon': mod.icon or 'fa-cubes',
                    'color': mod.color or '#4e73df',
                    'primary_tab': mod.primary_tab or 'patients',
                    'description': mod.description or '',
                    'submodules': subs
                })

            data.append({
                'id': r.id,
                'name': r.name,
                'description': r.description or '',
                'is_system': r.is_system,
                'user_count': user_count,
                'modules_count': modules_count,
                'submodules_count': submodules_count,
                'modules': modules_data,
                'created_at': r.created_at.isoformat() if r.created_at else None,
            })
        return Response(data)

    def post(self, request):
        name = request.data.get('name', '').strip()
        description = request.data.get('description', '').strip()

        if not name:
            return Response({'detail': 'Department name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if Role.objects.filter(name__iexact=name).exists():
            return Response({'detail': f'Department "{name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            cat, _ = Category.objects.get_or_create(department=name)
            role = Role.objects.create(
                name=name,
                description=description,
                category=cat,
                is_system=False
            )

        return Response({
            'detail': f'Department "{name}" created successfully in database!',
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'is_system': role.is_system,
                'user_count': 0,
                'modules_count': 0,
                'submodules_count': 0,
            }
        }, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def put(self, request, pk):
        try:
            role = Role.objects.get(id=pk)
        except Role.DoesNotExist:
            return Response({'detail': 'Department not found.'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        description = request.data.get('description', '').strip()

        if not name:
            return Response({'detail': 'Department name cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        if Role.objects.filter(name__iexact=name).exclude(id=pk).exists():
            return Response({'detail': f'Another department named "{name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            old_name = role.name
            role.name = name
            role.description = description
            role.save()

            if role.category:
                role.category.department = name
                role.category.save()
            else:
                cat, _ = Category.objects.get_or_create(department=name)
                role.category = cat
                role.save()

        return Response({
            'detail': f'Department updated to "{name}" successfully in database.',
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'is_system': role.is_system,
            }
        })

    def delete(self, request, pk):
        try:
            role = Role.objects.get(id=pk)
        except Role.DoesNotExist:
            return Response({'detail': 'Department not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role.is_system or role.name.lower() in ['admin', 'cmd']:
            return Response({'detail': 'System core departments (Admin, CMD) cannot be deleted.'}, status=status.HTTP_400_BAD_REQUEST)

        user_count = User.objects.filter(role=role).count()
        if user_count > 0:
            return Response({'detail': f'Cannot delete department "{role.name}" because {user_count} staff members are currently assigned to it.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            role_name = role.name
            if role.category:
                role.category.delete()
            role.delete()

        return Response({'detail': f'Role "{role_name}" deleted successfully from database.'})


class SystemModuleListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        modules = SystemModule.objects.all().order_by('order', 'name').prefetch_related('submodules')
        data = []
        for m in modules:
            subs = m.submodules.all().order_by('order', 'name')
            data.append({
                'id': m.id,
                'code': m.code,
                'name': m.name,
                'icon': m.icon,
                'color': m.color,
                'primary_tab': m.primary_tab,
                'description': m.description or '',
                'order': m.order,
                'is_active': m.is_active,
                'submodules': [
                    {
                        'id': s.id,
                        'code': s.code,
                        'name': s.name,
                        'tab_key': s.tab_key or '',
                        'sub_tab': s.sub_tab or '',
                        'sub_sub_tab': s.sub_sub_tab or '',
                        'route': s.route or '',
                        'icon': s.icon,
                        'description': s.description or '',
                        'order': s.order,
                        'is_active': s.is_active,
                    }
                    for s in subs
                ]
            })
        return Response(data)

    def post(self, request):
        name = request.data.get('name', '').strip()
        code = request.data.get('code', '').strip().lower().replace(' ', '_')
        icon = request.data.get('icon', 'fa-cubes').strip()
        color = request.data.get('color', '#4e73df').strip()
        primary_tab = request.data.get('primary_tab', '').strip() or code
        description = request.data.get('description', '').strip()
        order = request.data.get('order', 0)

        if not name or not code:
            return Response({'detail': 'Module name and code are required.'}, status=status.HTTP_400_BAD_REQUEST)

        if SystemModule.objects.filter(code=code).exists():
            return Response({'detail': f'Module with code "{code}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = 0

        mod = SystemModule.objects.create(
            name=name,
            code=code,
            icon=icon,
            color=color,
            primary_tab=primary_tab,
            description=description,
            order=order_val,
            is_active=True,
        )

        # Grant newly created module to Admin and CMD automatically
        for sys_role_name in ['Admin', 'CMD']:
            r = Role.objects.filter(name__iexact=sys_role_name).first()
            if r:
                RolePermission.objects.get_or_create(role=r, module=mod)

        return Response({
            'detail': f'Module "{name}" created successfully in database!',
            'module': {
                'id': mod.id,
                'code': mod.code,
                'name': mod.name,
                'icon': mod.icon,
                'color': mod.color,
                'primary_tab': mod.primary_tab,
                'description': mod.description,
                'order': mod.order,
                'submodules': [],
            }
        }, status=status.HTTP_201_CREATED)


class SystemModuleDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def put(self, request, pk):
        try:
            mod = SystemModule.objects.get(id=pk)
        except SystemModule.DoesNotExist:
            return Response({'detail': 'Module not found.'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        icon = request.data.get('icon', mod.icon).strip()
        color = request.data.get('color', mod.color).strip()
        primary_tab = request.data.get('primary_tab', mod.primary_tab).strip()
        description = request.data.get('description', '').strip()
        order = request.data.get('order', mod.order)

        if not name:
            return Response({'detail': 'Module name cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = mod.order

        mod.name = name
        mod.icon = icon
        mod.color = color
        mod.primary_tab = primary_tab
        mod.description = description
        mod.order = order_val
        mod.save()

        return Response({
            'detail': f'Module "{name}" updated successfully in database.',
            'module': {
                'id': mod.id,
                'code': mod.code,
                'name': mod.name,
                'icon': mod.icon,
                'color': mod.color,
                'primary_tab': mod.primary_tab,
                'description': mod.description,
                'order': mod.order,
            }
        })

    def delete(self, request, pk):
        try:
            mod = SystemModule.objects.get(id=pk)
        except SystemModule.DoesNotExist:
            return Response({'detail': 'Module not found.'}, status=status.HTTP_404_NOT_FOUND)

        mod_name = mod.name
        mod.delete()
        return Response({'detail': f'Module "{mod_name}" and its submodules deleted from database.'})


class SubModuleView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        module_id = request.data.get('module_id')
        name = request.data.get('name', '').strip()
        code = request.data.get('code', '').strip().replace(' ', '_')
        tab_key = request.data.get('tab_key', '').strip()
        sub_tab = request.data.get('sub_tab', '').strip()
        sub_sub_tab = request.data.get('sub_sub_tab', '').strip()
        route = request.data.get('route', '').strip()
        icon = request.data.get('icon', 'fa-circle').strip()
        description = request.data.get('description', '').strip()
        order = request.data.get('order', 0)

        if not module_id or not name or not code:
            return Response({'detail': 'Module ID, Submodule name, and Submodule code are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            mod = SystemModule.objects.get(id=module_id)
        except SystemModule.DoesNotExist:
            return Response({'detail': 'Target parent module does not exist.'}, status=status.HTTP_404_NOT_FOUND)

        if SubModule.objects.filter(module=mod, code=code).exists():
            return Response({'detail': f'Submodule with code "{code}" already exists in module "{mod.name}".'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = 0

        sub = SubModule.objects.create(
            module=mod,
            name=name,
            code=code,
            tab_key=tab_key or mod.primary_tab,
            sub_tab=sub_tab,
            sub_sub_tab=sub_sub_tab,
            route=route,
            icon=icon,
            description=description,
            order=order_val,
            is_active=True,
        )

        # Automatically grant new submodule to roles that currently have permissions on this parent module
        for perm in RolePermission.objects.filter(module=mod):
            perm.submodules.add(sub)

        return Response({
            'detail': f'Submodule "{name}" created under "{mod.name}" successfully in database!',
            'submodule': {
                'id': sub.id,
                'module_id': mod.id,
                'code': sub.code,
                'name': sub.name,
                'tab_key': sub.tab_key,
                'sub_tab': sub.sub_tab,
                'sub_sub_tab': sub.sub_sub_tab,
                'route': sub.route or '',
                'icon': sub.icon,
                'description': sub.description,
                'order': sub.order,
            }
        }, status=status.HTTP_201_CREATED)

    def put(self, request, pk):
        try:
            sub = SubModule.objects.get(id=pk)
        except SubModule.DoesNotExist:
            return Response({'detail': 'Submodule not found.'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        tab_key = request.data.get('tab_key', sub.tab_key).strip()
        sub_tab = request.data.get('sub_tab', sub.sub_tab).strip()
        sub_sub_tab = request.data.get('sub_sub_tab', sub.sub_sub_tab).strip()
        route = request.data.get('route', sub.route or '').strip()
        icon = request.data.get('icon', sub.icon).strip()
        description = request.data.get('description', '').strip()
        order = request.data.get('order', sub.order)
        new_module_id = request.data.get('module_id')

        if not name:
            return Response({'detail': 'Submodule name cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        # Handle updating parent module if specified
        if new_module_id:
            try:
                new_mod = SystemModule.objects.get(id=new_module_id)
            except SystemModule.DoesNotExist:
                return Response({'detail': 'Selected parent module does not exist.'}, status=status.HTTP_404_NOT_FOUND)

            if new_mod.id != sub.module_id:
                if SubModule.objects.filter(module=new_mod, code=sub.code).exclude(id=sub.id).exists():
                    return Response({
                        'detail': f'Submodule with code "{sub.code}" already exists in module "{new_mod.name}".'
                    }, status=status.HTTP_400_BAD_REQUEST)

                old_mod = sub.module
                sub.module = new_mod

                # Migrate permissions: for any role that currently has this submodule assigned,
                # attach it to the role's permission for new_mod
                for old_rp in RolePermission.objects.filter(module=old_mod, submodules=sub):
                    old_rp.submodules.remove(sub)
                    new_rp, _ = RolePermission.objects.get_or_create(role=old_rp.role, module=new_mod)
                    new_rp.submodules.add(sub)

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = sub.order

        sub.name = name
        sub.tab_key = tab_key
        sub.sub_tab = sub_tab
        sub.sub_sub_tab = sub_sub_tab
        sub.route = route
        sub.icon = icon
        sub.description = description
        sub.order = order_val
        sub.save()

        return Response({
            'detail': f'Submodule "{name}" updated successfully in database.',
            'submodule': {
                'id': sub.id,
                'module_id': sub.module.id,
                'code': sub.code,
                'name': sub.name,
                'tab_key': sub.tab_key,
                'sub_tab': sub.sub_tab,
                'sub_sub_tab': sub.sub_sub_tab,
                'route': sub.route or '',
                'icon': sub.icon,
                'description': sub.description,
                'order': sub.order,
            }
        })

    def delete(self, request, pk):
        try:
            sub = SubModule.objects.get(id=pk)
        except SubModule.DoesNotExist:
            return Response({'detail': 'Submodule not found.'}, status=status.HTTP_404_NOT_FOUND)

        sub_name = sub.name
        sub.delete()
        return Response({'detail': f'Submodule "{sub_name}" deleted successfully from database.'})


class RolePermissionView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        role_id = request.query_params.get('role_id')
        if not role_id:
            return Response({'detail': 'Query parameter "role_id" is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            role = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return Response({'detail': 'Role not found.'}, status=status.HTTP_404_NOT_FOUND)

        perms = RolePermission.objects.filter(role=role).select_related('module').prefetch_related('submodules')
        
        assigned_modules = []
        assigned_submodules = {}

        for p in perms:
            assigned_modules.append(p.module.id)
            assigned_submodules[p.module.id] = list(p.submodules.values_list('id', flat=True))

        return Response({
            'role_id': role.id,
            'role_name': role.name,
            'is_system': role.is_system,
            'assigned_modules': assigned_modules,
            'assigned_submodules': assigned_submodules,
        })

    def post(self, request):
        role_id = request.data.get('role_id')
        assignments = request.data.get('assignments', [])

        if not role_id:
            return Response({'detail': 'Role ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            role = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return Response({'detail': 'Role not found.'}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            # Clear old permissions for this role
            RolePermission.objects.filter(role=role).delete()

            granted_module_codes = []

            for item in assignments:
                mod_id = item.get('module_id')
                sub_ids = item.get('submodule_ids', [])

                try:
                    mod = SystemModule.objects.get(id=mod_id)
                except SystemModule.DoesNotExist:
                    continue

                perm = RolePermission.objects.create(role=role, module=mod)
                granted_module_codes.append(mod.code)

                if sub_ids:
                    subs = SubModule.objects.filter(id__in=sub_ids, module=mod)
                    perm.submodules.set(subs)

            # Sync with Category.modules for backwards compatibility
            if role.category:
                role.category.modules = granted_module_codes
                role.category.save()
            else:
                cat, _ = Category.objects.get_or_create(department=role.name)
                cat.modules = granted_module_codes
                cat.save()
                role.category = cat
                role.save()

        return Response({
            'detail': f'Permissions for department "{role.name}" saved successfully to database!',
            'role_id': role.id,
            'assigned_modules_count': len(assignments),
        })


class UserRoleAssignmentView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user_id = request.data.get('user_id')
        role_id = request.data.get('role_id')

        if not user_id or not role_id:
            return Response({'detail': 'User ID and Department ID are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(id=user_id)
            role = Role.objects.get(id=role_id)
        except (User.DoesNotExist, Role.DoesNotExist):
            return Response({'detail': 'User or Department not found.'}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            user.role = role
            if role.category:
                user.department = role.category
            user.save()

        return Response({
            'detail': f'Department "{role.name}" assigned to staff "{user.fullname or user.username}" in database.',
            'user_id': user.id,
            'role_id': role.id,
            'role_name': role.name,
        })


class UserPermissionsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        user = request.user if request.user.is_authenticated else None
        
        # Fallback to requested user_id or query param if provided
        user_id = request.query_params.get('user_id')
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                pass

        if not user or not user.is_authenticated:
            # Return demo/default frontdesk permissions or first user
            user = User.objects.first()

        if not user:
            return Response({'detail': 'No user found.'}, status=status.HTTP_404_NOT_FOUND)

        role = user.role
        if not role:
            # Fallback to user department category
            dept_name = user.department.department if user.department else 'Admin'
            role = Role.objects.filter(name__iexact=dept_name).first()
            if not role:
                role = Role.objects.filter(name='Admin').first()

        if not role:
            return Response({'role': 'Admin', 'is_admin': True, 'modules': [], 'submodules': {}})

        is_admin = role.name.lower() in ['admin', 'cmd']

        perms = RolePermission.objects.filter(role=role).select_related('module').prefetch_related('submodules')
        
        allowed_modules = []
        allowed_submodules = {}

        for p in perms:
            allowed_modules.append(p.module.code)
            allowed_submodules[p.module.code] = list(p.submodules.values_list('code', flat=True))

        return Response({
            'user_id': user.id,
            'username': user.username,
            'role_id': role.id,
            'role_name': role.name,
            'is_admin': is_admin,
            'modules': allowed_modules,
            'submodules': allowed_submodules,
        })


class SeedRbacView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        seed_rbac()
        return Response({'detail': 'Default Modules, Submodules, Roles, and Permissions seeded successfully in database!'})
