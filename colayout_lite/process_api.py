"""Public configuration proposals. Approval is intentionally not an API action."""
from .process_package import ProcessPackage
from .model import LiteError
from pathlib import Path


def invoke(service,args,client_id,request_id):
    if args.action=='requirements':
        return {'schema':ProcessPackage.model_json_schema(),
            'sample':{'required':['saved business Layout','normal MOS/resistor samples and a native MIM capacitor (explicitly mark unsupported if the PDK has none)','top-level 1x1 via for each adjacent metal pair'],
                      'optional':['for each needed P/N guard type: one native open 90-degree MPP with straight segments, corners and both ends; double rows require real double-row samples']},
            'collection':{'native':'Virtuoso Bridge Lite: native layers/materials, DBU/grid, standard via definitions, sample MPP and CDF/XL evidence',
                          'rules':'Use the selected PDK DRC/runset/layer map; never infer thresholds from sample sizes. Local spacing is geometric, without same-net/different-net or net-name conditions. Enabled spacing rules on the same layer all apply, not as conditional branches. id/note/source do not execute conditions. Describe the actual simplification and omitted cases; configuration checks do not prove equivalence to the deck.',
                          'preferences':'metal order/default widths, preferred routing direction per metal, cut-count advisory, schematic summary fields',
                          'missing_materials':'Only native unknown/null materials may be supplemented from actual process evidence; collect --layer-materials records original values and sources for human review. Never infer roles from layer names.'},
            'mim_capacitor':'drc.mim_capacitor records status, native lpp, lower_metal, upper_metal and source. Resolve from a native MIM sample and actual process/extraction rules; unknown values require human confirmation before approval. Never guess metal names or mark unsupported because collection failed.',
            'connections':[{'id':key,'name':path.stem,'collection_connection_file':str(path),
                            'current':service.connection() is not None and path.resolve()==Path(service.connection()).resolve()} for key,path in service.connection_choices().items()],
            'workflow':'collect → native sample reproduction and file checks (no default DRC) → submit → human approval; layout DRC remains required separately',
            'sharing':'UI exports/imports one process JSON; Bridge credentials and host connection remain local',
            'double_guard_policy':'sample_only'}
    if args.action=='list':
        rows=[{'key':key,'name':entry['label'],'confirmed':entry.get('confirmed',False)} for key,entry in service.store.entries().items()]
        pending=[service.summary(path,data) for path,data in service.store.drafts() if data.get('schema_version')=='colayout-process-proposal-3']
        return {'configured':rows,'pending':pending}
    if args.action=='get':
        if args.proposal_id:
            path,data=service.proposal(args.proposal_id)
            return {**service.summary(path,data),'package':data['package'],'sample':data['source'],
                    'project_root':data.get('project_root')}
        return {'package':service.load(args.technology_key).model_dump(mode='json')}
    if args.action=='status':
        path,data=service.proposal(args.proposal_id);return service.summary(path,data)
    if args.action=='export':return service.export(args.technology_key)
    if args.action=='submit':
        return service.submit(args.package,args.sample,client_id=client_id,request_id=request_id,
                              connection_id=args.connection_id,project_root=args.project_root,verification_id=args.verification_id)
    raise LiteError('UNKNOWN_PROCESS_ACTION')
