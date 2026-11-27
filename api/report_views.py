"""Reporting page: live reports (rules in api/reports.py)."""
import csv
import io
from datetime import date

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.notification_views import _has_module
from api.reports import REPORTS, summary_tiles


def _period(request):
    """(first, last, error) from ?from=&to= (default: this month so far; at most 366 days)."""
    q = request.query_params
    today = timezone.localdate()
    try:
        first = date.fromisoformat(q['from']) if q.get('from') else today.replace(day=1)
        last = date.fromisoformat(q['to']) if q.get('to') else today
    except ValueError:
        return None, None, 'Dates must be YYYY-MM-DD.'
    if last < first:
        return None, None, 'The "to" date is before the "from" date.'
    if (last - first).days > 366:
        return None, None, 'Choose a period of one year or less.'
    return first, last, None


def _may_see(user, modules):
    return _has_module(user, 'reporting') or any(_has_module(user, m) for m in modules)


class ReportSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _has_module(request.user, 'reporting'):
            return Response({'error': 'Needs the Reporting module.'}, status=status.HTTP_403_FORBIDDEN)
        first, last, err = _period(request)
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'from': first.isoformat(), 'to': last.isoformat(), **summary_tiles(first, last)})


class ReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, key):
        entry = REPORTS.get(key)
        if not entry:
            return Response({'error': 'Unknown report.'}, status=status.HTTP_404_NOT_FOUND)
        category, fn, modules = entry
        if not _may_see(request.user, modules):
            return Response({'error': 'You do not have access to this report.'}, status=status.HTTP_403_FORBIDDEN)
        first, last, err = _period(request)
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
        data = fn(first, last, (request.query_params.get('q') or '').strip()[:100])
        data.update({'key': key, 'category': category, 'from': first.isoformat(), 'to': last.isoformat()})
        if request.query_params.get('export') == 'csv':
            return _csv(data)
        return Response(data)


def _csv(data):
    """Excel-friendly CSV (UTF-8 with BOM so ₦ and names show correctly)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([data['title'], f"{data['from']} to {data['to']}"])
    for s in data.get('summary') or []:
        w.writerow([s['label'], s['value']])
    w.writerow([])
    cols = data['columns']
    w.writerow([c['label'] for c in cols])
    for r in data['rows']:
        out = []
        for c in cols:
            v = r.get(c['key'])
            if v is None:
                v = ''
            elif c['type'] == 'datetime' and v:
                v = str(v)[:16].replace('T', ' ')
            # keep a leading = + - @ from being read as a spreadsheet formula
            if isinstance(v, str) and v[:1] in ('=', '+', '-', '@'):
                v = "'" + v
            out.append(v)
        w.writerow(out)
    if data.get('truncated'):
        w.writerow([f"Only the first {len(data['rows'])} of {data['count']} rows are included; narrow the dates."])
    resp = HttpResponse('﻿' + buf.getvalue(), content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{data["key"]}_{data["from"]}_{data["to"]}.csv"'
    return resp
