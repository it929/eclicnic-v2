"""System health for administrators."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from clinic365.backup_health import backup_health
from inventory.permissions import is_admin


class BackupStatusView(APIView):
    """GET system/backup-status/: are backups running, off-site and restorable? Admin/CMD only."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_admin(request.user):
            return Response({'error': 'Administrators only.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(backup_health())
