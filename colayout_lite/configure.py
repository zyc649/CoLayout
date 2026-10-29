"""Discover a process profile. Human/Agent reviews declarative settings."""
import argparse
from pathlib import Path
from .adapter import Adapter
from .paths import ROOT
from .transport import NativeTransport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',required=True);parser.add_argument('--cell',required=True)
    parser.add_argument('--name',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--connection',type=Path,default=ROOT/'config/colayout_lite.json')
    args=parser.parse_args()
    from .codec import decode
    native=NativeTransport(args.connection);snapshot,p=decode(native.read(args.library,args.cell))
    p=p.model_copy(update={'id':args.name,'label':args.name})
    p.save(args.output)
    print(f'Profile saved: {args.output}; layers={len(p.writable_lpps)}, vias={len(p.vias)}, guard templates={len(p.guard_templates)}')
    print('Discovered configuration is not physical-rule sign-off. Review writable layers and run native regression.')


if __name__=='__main__':main()
