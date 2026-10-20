import sys,os; sys.path.insert(0, os.path.dirname(__file__)); import swfparse as P, render as Rn
swf=P.parse(sys.argv[1]); out=sys.argv[2]
for fr in map(int, sys.argv[3:]):
    sv=Rn.SVG(swf); body=sv.displaylist(swf['main']['frames'], fr)
    doc=sv.document(body, swf['stage'], swf['bg'])
    open(f'{out}/main_{fr:03d}.svg','w').write(doc); Rn.png(doc, f'{out}/main_{fr:03d}.png')
    print(fr,'ok',len(doc))
