"""Routing/check/capture orchestration; leases and worker lifetimes are separate services."""

from pathlib import Path
from threading import Event
from uuid import uuid4
from ..model import LiteError
from ..document import save_document
from ..transactions import write_json_atomic
from ..autoroute.service import RoutingSession
from ..autoroute.plugins import Registry
from ..autoroute import runner
from .jobs import Job


class RegionTasks:
    def __init__(self, registry, ownership, folder, *, busy, saved, capture):
        self.registry = registry
        self.actor = ownership.actor
        self.folder = Path(folder)
        self.busy = busy
        self.saved = saved
        self.capture = capture
        self.drc_source = registry.drc

    def route_region(self, lease, args):
        from ..autoroute.usage import BUILTIN_ROUTING_ADVICE
        result=self._route_region(lease,args)
        return {**result,'advisories':[{'code':'BUILTIN_ROUTING_ANALOG_CAUTION','message':BUILTIN_ROUTING_ADVICE}]}

    def _route_region(self, lease, args):
        e = lease.editor
        if args.action == 'generate':
            rules = self.registry.available(lease, self.busy)
            algorithms = Registry(self.folder / 'builtin-only.json').resolve(args.algorithms)
            with self.actor(lease, args.expected_revision):
                session = RoutingSession(
                    e, rules, lease.region_id, self.folder / 'jobs', layers=args.layers
                )
            job = Job(
                session.id,
                lease,
                'route',
                e.w,
                e.profile,
                rules,
                session.folder,
                session.cancelled,
                routing=session,
            )

            def progress(message):
                self.registry.progress(job, message)

            return self.registry.submit(job, lambda: session.generate(algorithms, progress))
        job = self.registry.get(lease, args.job_id, 'route')
        if args.action == 'status':
            return self.registry.status(job)
        if args.action == 'discard':
            self.registry.cancel(job)
            return {'discarded': job.id}
        if args.action == 'recheck':
            rules = self.registry.available(lease, self.busy)
            candidate = job.routing.candidates.get(args.candidate_id) if job.routing else None
            if job.state != 'completed' or candidate is None:
                raise LiteError('ROUTING_CANDIDATE_UNKNOWN')
            with self.actor(lease, args.expected_revision):
                session = RoutingSession(
                    e,
                    rules,
                    lease.region_id,
                    self.folder / 'jobs',
                    layers=job.routing.selected_layers,
                )
            fresh = Job(
                session.id,
                lease,
                'route',
                e.w,
                e.profile,
                rules,
                session.folder,
                session.cancelled,
                routing=session,
            )

            def progress(message):
                self.registry.progress(fresh, message)

            return self.registry.submit(fresh, lambda: session.recheck(candidate, progress))
        if self.busy():
            raise LiteError('WORKSPACE_BUSY')
        if job.state != 'completed' or not self.registry.current(job):
            raise LiteError('ROUTING_STALE', '候选尚未完成或工作区已改变，请重检或重新生成。')
        with self.actor(lease, args.expected_revision):
            result = job.routing.apply(e, args.candidate_id, self.drc_source())
            if not result['no_op']:
                lease.history.append(e.history_token())
        return self.saved(result)

    def check_region(self, lease, args):
        if args.action == 'status':
            job=self.registry.get(lease,args.job_id,'check')
            return self.registry.status(job)
        rules = self.registry.available(lease, self.busy)
        e = lease.editor
        with self.actor(lease, args.expected_revision):
            from ..drc.scope import authorized_region
            roi=authorized_region(e.w,e.profile,lease.region_id,args.bounds_um)
            ident = uuid4().hex
            folder = self.folder / 'jobs' / ident
            folder.mkdir(parents=True)
            save_document(folder / 'source.colayout.json', e.w, e.profile)
            request = folder / 'check.json'
            write_json_atomic(
                request,
                {
                    'document': str(folder / 'source.colayout.json'),
                    'region_id': lease.region_id,
                    'bounds_um': [v/e.profile.dbu_per_micron for point in roi.bbox for v in point],
                    'drc': rules.model_dump(mode='json'),
                },
            )
            job = Job(ident, lease, 'check', e.w, e.profile, rules, folder, Event())

        def run():
            self.registry.progress(job, '检查 Layout 连通性与本地 DRC…')
            return runner.run(
                [
                    runner.python_executable(),
                    '-X',
                    'utf8',
                    '-m',
                    'colayout_lite.agent_tools.worker',
                    str(request),
                    str(folder / 'result.json'),
                ],
                folder / 'result.json',
                folder / 'check.log',
                job.cancelled,
                180,
            )

        return self.registry.submit(job, run)

    def server_drc_region(self, lease, args):
        if args.action!='start' and args.result_limit is not None:
            raise LiteError('INVALID_ARGUMENTS','result_limit 只用于重新启动检查，不会改变已有报告。')
        from . import server_drc
        if args.action == 'start':
            if self.drc_source() is None:
                raise LiteError('REMOTE_DRC_NOT_CONFIGURED', '请由人在工艺设置中配置服务器DRC。')
            rules = self.registry.available(lease, self.busy)
            if rules.remote is None:
                raise LiteError('REMOTE_DRC_NOT_CONFIGURED', '请由人在工艺设置中配置服务器DRC。')
            e = lease.editor
            with self.actor(lease, args.expected_revision):
                roi = server_drc.authorized_region(e.w, e.profile, lease.region_id, args.bounds_um)
                ident = uuid4().hex
                folder = self.folder / 'jobs' / ident
                folder.mkdir(parents=True)
                job = Job(ident, lease, 'server_drc', e.w, e.profile, rules, folder, Event())
            def execute():
                options={'result_limit':args.result_limit} if args.result_limit is not None else {}
                result=server_drc.run(job, roi, lambda message: self.registry.progress(job, message),**options)
                return result
            self.registry.submit(job, execute)
        else:
            job = self.registry.get(lease, args.job_id, 'server_drc')
            if args.action == 'cancel':
                self.registry.cancel(job)
        status = self.registry.status(job,server_options={'excluded':args.exclude_categories,
            'offset':args.offset,'limit':args.limit,'include_waived':args.include_waived})
        if job.state == 'completed':
            from .release_status import verification_registry
            status['verification']=verification_registry(self.registry,lease)
        return status

    def capture_region(self, lease, args):
        workspace=self.capture_workspace(lease,args)
        return self.capture(workspace, lease.editor.profile, lease.region_id, args, self.folder / 'images')

    def capture_workspace(self,lease,args):
        if self.capture is None:
            raise LiteError('CAPTURE_UNAVAILABLE')
        if self.busy():
            raise LiteError('WORKSPACE_BUSY')
        e = lease.editor
        workspace = e.w
        if bool(args.job_id) != bool(args.candidate_id):
            raise LiteError('INVALID_ARGUMENTS','job_id 与 candidate_id 必须同时提供。')
        if args.job_id:
            job = self.registry.get(lease, args.job_id, 'route')
            if not self.registry.current(job) or job.state != 'completed':
                raise LiteError('ROUTING_STALE')
            candidate = job.routing.candidates.get(args.candidate_id) if job.routing else None
            if candidate is None:
                raise LiteError('ROUTING_CANDIDATE_UNKNOWN')
            from ..autoroute.preview import RoutingPreview

            with self.actor(lease, e.w.revision):
                workspace = RoutingPreview(e, job.routing, candidate).workspace
        return workspace
