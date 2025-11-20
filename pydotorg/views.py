import datetime as dt
import json
import os
import requests
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.generic.base import RedirectView, TemplateView

from codesamples.models import CodeSample
from downloads.models import Release


def health(request):
    return HttpResponse('OK')


def serve_funding_json(request):
    """Serve the funding.json file from the static directory."""
    funding_json_path = os.path.join(settings.BASE, 'static', 'funding.json')
    try:
        with open(funding_json_path, 'r') as f:
            data = json.load(f)
        return JsonResponse(data)
    except FileNotFoundError:
        return JsonResponse({'error': 'funding.json not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in funding.json'}, status=500)


class IndexView(TemplateView):
    template_name = "python/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update({
            'code_samples': CodeSample.objects.published()[:5],
        })
        return context


class AuthenticatedView(TemplateView):
    template_name = "includes/authenticated.html"


class DocumentationIndexView(TemplateView):
    template_name = 'python/documentation.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'latest_python2': Release.objects.latest_python2(),
            'latest_python3': Release.objects.latest_python3(),
        })
        return context


class MediaMigrationView(RedirectView):
    prefix = None
    permanent = True
    query_string = False

    def get_redirect_url(self, *args, **kwargs):
        image_path = kwargs['url']
        if self.prefix:
            image_path = '/'.join([self.prefix, image_path])
        return '/'.join([
            settings.AWS_S3_ENDPOINT_URL,
            settings.AWS_STORAGE_BUCKET_NAME,
            image_path,
        ])


class DocsByVersionView(TemplateView):
    template_name = 'python/versions2.html'  # TODO remove the 2

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Fetch data from the Python releases API
        try:
            response = requests.get(
                'https://peps.python.org/api/python-releases.json', timeout=10
            )
            response.raise_for_status()
            data = response.json()

            # Get metadata and releases
            metadata = data.get('metadata', {})
            releases = data.get('releases', {})

            # Create a list of versions with their data
            version_list = []

            for version in releases.keys():
                version_releases = releases.get(version, [])

                # Filter to only include actual releases (not expected)
                actual_releases = [
                    r for r in version_releases if r.get('state') == 'actual'
                ]

                # Versions without documentation
                no_docs = {'2.3.6', '2.3.7', '2.4.5', '2.4.6', '2.5.5', '2.5.6'}

                # Filter out alpha, beta, and release candidates
                stable_releases = []
                for r in actual_releases:
                    stage = r.get('stage', '')
                    if stage and not any(
                        keyword in stage.lower()
                        for keyword in ['alpha', 'beta', 'rc', 'candidate']
                    ):
                        if stage in no_docs:
                            continue

                        r = r.copy()

                        # Remove ' final' suffix if present
                        if stage.endswith(' final'):
                            stage = stage[:-6]
                            r['stage'] = stage

                        # Special case: for 3.2.0 and earlier, use X.Y instead of X.Y.0
                        try:
                            version_parts = stage.split('.')
                            if len(version_parts) == 3:
                                major, minor, patch = map(int, version_parts)
                                # For versions <= 3.2.0 where patch is 0
                                if (major, minor, patch) <= (3, 2, 0) and patch == 0:
                                    r['stage'] = f'{major}.{minor}'
                        except (ValueError, IndexError):
                            pass

                        stable_releases.append(r)

                # Skip versions that don't have stable releases
                if not stable_releases:
                    continue

                # Sort releases by date (newest first) before formatting
                stable_releases = sorted(
                    stable_releases, key=lambda x: x.get('date', ''), reverse=True
                )

                # Format dates after sorting
                for r in stable_releases:
                    date_str = r.get('date', '')
                    if date_str and '-' in date_str:
                        try:
                            date_obj = dt.datetime.strptime(date_str, '%Y-%m-%d')
                            r['date'] = date_obj.strftime('%-d %B %Y')
                        except ValueError:
                            pass

                # Get metadata for this version
                version_meta = metadata.get(version, {})

                version_list.append(
                    {
                        'version': version,
                        'releases': stable_releases,
                        'metadata': version_meta,
                    }
                )

            # Add special legacy releases not in the API
            legacy_releases = [
                {
                    'version': '1.5',
                    'releases': [
                        {'stage': '1.5.2p2', 'date': '22 March 2000'},
                        {'stage': '1.5.2p1', 'date': '6 July 1999'},
                        {'stage': '1.5.2', 'date': '30 April 1999'},
                        {'stage': '1.5.1p1', 'date': '6 August 1998'},
                        {'stage': '1.5.1', 'date': '14 April 1998'},
                        {'stage': '1.5', 'date': '17 February 1998'},
                    ],
                    'metadata': {},
                },
                {
                    'version': '1.4',
                    'releases': [
                        {'stage': '1.4', 'date': '25 October 1996'},
                    ],
                    'metadata': {},
                },
            ]
            version_list.extend(legacy_releases)

            # Sort versions (newest first)
            version_list.sort(
                key=lambda x: [
                    int(n) if n.isdigit() else n for n in x['version'].split('.')
                ],
                reverse=True,
            )

            context.update({
                'version_list': version_list,
            })
        except Exception as e:
            context.update({
                'error': str(e),
                'version_list': [],
            })

        return context
