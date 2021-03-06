# provide commands for Fragment Analysis (FA)

from fatools.lib import params
from fatools.lib.utils import cerr, cout, cverr, cexit, tokenize, detect_buffer, set_verbosity
from fatools.lib.fautil.mixin2 import LadderMismatchException

import sys, argparse, yaml, csv, os
from io import StringIO

def init_argparser(parser=None):

    p = parser if parser else argparse.ArgumentParser('facmd')

    p.add_argument('--sqldb', default=False,
            help = 'SQLite3 database filename')

    p.add_argument('--file', default=None,
            help = "Comma-separated FSA filenames (optional)")

    p.add_argument('--indir', default=False,
            help = 'input directory (eg. containing FSA files)')

    p.add_argument('--fsdb', default=None,
            help = 'Filesystem-based database')

    p.add_argument('--infile', default=None,
            help = 'Tab-delimited or CSV manifest file')

    p.add_argument('--outfile', default='-',
            help = 'output filename')

    # command in ascending order

    p.add_argument('--clear', default=False, action='store_true',
            help = 'clear (or remove) all peaks from FSA file')

    p.add_argument('--align', default=False, action='store_true',
            help = 'scan ladder channel, preannotate and align with size standards')

    p.add_argument('--call', default=False, action='store_true',
            help = 'scan non-ladder channels, preannotate peaks and determine their sizes')

    p.add_argument('--bin', default=False, action='store_true',
            help = 'bin non-ladder peaks')

    p.add_argument('--annotate', default=False, action='store_true',
            help = 'annotate non-ladder peaks')

    p.add_argument('--plot', default=False, action='store_true',
            help = 'plot normalized trace')

    p.add_argument('--ladderplot', default=False, action='store_true',
            help = 'plot ladder peaks and calibration curve')

    p.add_argument('--dendogram', default=False, action='store_true',
            help = 'plot dendograms of ladders and alleles')

    p.add_argument('--listpeaks', default=False, action='store_true',
            help = 'list all peaks')

    p.add_argument('--peaks_format', default="standard",
                   help = "format for peaks output file (standard, peakscanner)")
    
    # semi-mandatory

    p.add_argument('--panel', default="",
            help = 'comma-separated panel code(s)')

    p.add_argument('--marker', default="",
            help = 'comma-separated marker code(s)')

    p.add_argument('--panelfile', default="",
            help = 'YAML panel file')

    p.add_argument('--markerfile', default="",
            help = "YAML marker file")

    # options

    p.add_argument('--cluster', default=0, type=int,
            help = 'number of cluster for hierarchical clustering alignment')

    p.add_argument('--verbose', default=0, type=int,
            help = 'show verbosity')

    p.add_argument('--use-cache', default=False, action='store_true',
            help = 'prepare to use caches')

    p.add_argument('--no-cache', default=False, action='store_true',
            help = 'do not use caches')

    p.add_argument('--commit', default=False, action='store_true',
            help = 'commit to database')

    ## Override params

    p.add_argument('--ladder_rfu_threshold', default=-1, type=float,
                   help='ladder rfu threshold')

    p.add_argument('--nonladder_rfu_threshold', default=-1, type=float,
                   help='nonladder rfu threshold')

    p.add_argument('--allelemethod', default='', type=str,
                   help='allele method (leastsquare, cubicspline, localsouthern)')

    p.add_argument('--baselinemethod', default='median', type=str,
                   help='baseline method (none, median, minimum)')

    p.add_argument('--baselinewindow', default=399, type=int,
                   help='size of running window for baseline determination (default 399)')

    return p


def main(args):

    if args.verbose != 0:
        set_verbosity(args.verbose)

    dbh = None

    # set parameter for baseline correction and allelemethod
    from fatools.lib.const import allelemethod, baselinemethod
    _params = params.Params()

    _params.baselinewindow = args.baselinewindow 

    if args.baselinemethod !="":
        if args.baselinemethod=='none':
            _params.baselinemethod = baselinemethod.none
        elif args.baselinemethod=='median':
            _params.baselinemethod = baselinemethod.median
        elif args.baselinemethod=='minimum':
            _params.baselinemethod = baselinemethod.minimum
        else:
            raise NotImplementedError()

    if args.allelemethod !="":
        if args.allelemethod=='leastsquare':
            _params.allelemethod = allelemethod.leastsquare
        elif args.allelemethod=='cubicspline':
            _params.allelemethod = allelemethod.cubicspline
        elif args.allelemethod=='localsouthern':
            _params.allelemethod = allelemethod.localsouthern
        else:
            raise NotImplementedError()

    if args.file or args.infile or args.indir:
        cverr(4, 'D: opening FSA file(s)')
        fsa_list = open_fsa(args, _params)
    elif dbh is None:
        cverr(4, 'D: connecting to database')
        dbh = get_dbhandler(args)
        fsa_list = get_fsa_list(args, dbh)

    cerr('I: obtained %d FSA' % len(fsa_list))

    if args.commit:
        with transaction.manager:
            do_facmd(args, fsa_list, dbh)
            cerr('** COMMIT to database **')
    elif dbh:
        cerr('WARNING ** running without database COMMIT! All changes will be discarded!')
        if not ( args.test or args.y ):
            keys = input('Do you want to continue [y/n]? ')
            if not keys.lower().strip().startswith('y'):
                sys.exit(1)
        do_facmds(args, fsa_list, _params, dbh)
    else:
        do_facmds(args, fsa_list, _params)

        
def do_facmds(args, fsa_list, params, dbh=None):

    bad_files_filename = args.indir + "/" + args.indir + "_badfiles.out"

    f_bad_files = open(bad_files_filename,'w')
    
    executed = 0
    if args.clear:
        do_clear( args, fsa_list, dbh )
        executed += 1
    if args.align:
        do_align( args, fsa_list, f_bad_files, dbh )
        executed += 1
    if args.call:
        do_call( args, fsa_list, params, dbh )
        executed += 1
    if args.plot:
        do_plot( args, fsa_list, dbh )
        executed += 1
    if args.dendogram:
        do_dendogram( args, fsa_list, dbh)
        executed += 1
    if args.ladderplot:
        do_ladderplot( args, fsa_list, dbh )
        executed += 1
    if args.listpeaks is not False:
        do_listpeaks( args, fsa_list, dbh )
        executed += 1

    if executed == 0:
        cerr('W: please provide a relevant command')
    else:
        cerr('I: executed %d command(s)' % executed)

    f_bad_files.close()
    
def do_clear( args, fsa_list, dbh ):
    pass


def do_align( args, fsa_list, f_bad_files, dbh ):

    _params = params.Params()
    if args.ladder_rfu_threshold >= 0:
        _params.ladder.min_rfu = args.ladder_rfu_threshold

    cerr('I: Aligning size standards...')

    for (fsa, sample_code) in fsa_list:
        cverr(3, 'D: aligning FSA %s' % fsa.filename)
        try:
            fsa.align(_params)
        except LadderMismatchException:
            f_bad_files.write(("LadderMismatch: %s\n") % fsa.filename)
            continue

def do_call( args, fsa_list, params, dbh ):

    cerr('I: Calling non-ladder peaks...')

    if args.nonladder_rfu_threshold >= 0:
        params.nonladder.min_rfu = args.nonladder_rfu_threshold


    for (fsa, sample_code) in fsa_list:
        cverr(3, 'D: calling FSA %s' % fsa.filename)
        fsa.call(params)


def do_plot( args, fsa_list, dbh ):

    cerr('I: Creating plot...')

    from matplotlib import pylab as plt

    for (fsa, sample_code) in fsa_list:
        for c in fsa.channels:
            plt.plot(c.data)

        plt.show()

def do_ladderplot( args, fsa_list, dbh ):

    cerr('I: Creating ladder plot...')

    import matplotlib.pyplot as plt
    for (fsa, sample_code) in fsa_list:

        c = fsa.get_ladder_channel()

        # get ladder and times for peaks fit to ladder
        ladder_sizes = fsa.panel.get_ladder()['sizes']
        alleles = c.get_alleles()
        allele_sizes = [allele.rtime for allele in alleles]

        plt.plot(allele_sizes, ladder_sizes, 'p', label='peaks matched to ladder steps')

        # plot fit of ladder scan times to base pairs
        import numpy as  np
        fit = np.poly1d(c.fsa.z)
        #x = np.arange(allele_sizes[0] - 150, allele_sizes[-1] + 100)  # len(c.data))
        x = np.arange(800, allele_sizes[-1] + 100)  # len(c.data))
        plt.plot(x, fit(x), label='fitted curve')
        plt.legend()
        plt.xlabel("peak scan times")
        plt.ylabel("# base pairs")

    plt.show()

def do_dendogram( args, fsa_list, dbh ):

    from fatools.lib.fautil import hcalign
    from matplotlib import pyplot as plt

    for (fsa, sample_code) in fsa_list:

        c = fsa.get_ladder_channel()
        c.scan(params.Params()) # scan first if necessary

        ladder = fsa.panel.get_ladder()
        peaks = c.get_alleles()

        #initial_pair, P, L = hclustalign.hclust_align(peaks, ladder)
        P = hcalign.generate_tree( [ (n.rtime, 0) for n in peaks ] )
        L = hcalign.generate_tree( [ (e, 0) for e in ladder['sizes'] ] )

        clusters = hcalign.fcluster(L.z, args.cluster or ladder['k'], criterion="maxclust")
        print(clusters)

        clusters = hcalign.fcluster(P.z, args.cluster or ladder['k'], criterion="maxclust")
        print(clusters)

        plt.figure()
        plt.subplot(121)
        hcalign.dendrogram(L.z, leaf_rotation=90, leaf_font_size=8,
                labels = [ x[0] for x in L.p ])
        plt.subplot(122)
        hcalign.dendrogram(P.z, leaf_rotation=90, leaf_font_size=8,
                labels = [ x[0] for x in P.p ])
        plt.show()


def do_listpeaks( args, fsa_list, dbh ):

    if args.outfile != '-':
        out_stream = open(args.outfile, 'w')
    else:
        out_stream = sys.stdout

    if args.peaks_format=='standard':
        out_stream.write('SAMPLE\tFILENAME   \tDYE\tRTIME\tSIZE\tHEIGHT\tAREA\tSCORE\n')
    elif args.peaks_format == 'peakscanner':
        out_stream.write("Dye/Sample Peak,Sample File Name,Size,Height,Area in Point,Area in BP,Data Point,Begin Point,")
        out_stream.write("Begin BP,End Point,End BP,Width in Point,Width in BP,User Comments,User Edit\n")

    else:
        raise RuntimeError("Unknown value for args.peaks_format")
    out_stream.close()

    for (fsa, sample_code) in fsa_list:
        cverr(3, 'D: calling FSA %s' % fsa.filename)

        markers = fsa.panel.data['markers']

        out_stream = open(args.outfile, 'a')
        for channel in fsa.channels:
            if channel.is_ladder():
                continue

            color = markers["x/"+channel.dye]['filter']

            #cout('Marker => %s | %s [%d]' % (channel.marker.code, channel.dye,
            #       len(channel.alleles)))
            #cout("channel has alleles :",len(channel.alleles))
            i=1
            for p in channel.alleles:

                if args.peaks_format=='standard':
                    out_stream.write('%6s\t%10s\t%3s\t%d\t%d\t%5i\t%3.2f\t%3.2f\n' %
                                     (sample_code, fsa.filename[:-4], color, p.rtime, p.size, p.height, p.area, p.qscore))
                else:
                    out_stream.write('"%s, %i",%s, %f, %i, %i, %i, %i, %i, %f, %i, %f, %i, %f,,\n' %
                                    #(color, i+1, fsa.filename, size_bp, height,area_s, area_bp, size_s, begin_s, begin_bp, end_s, end_bp, width_s, width_bp))
                                     (color, i, fsa.filename, p.size, p.height, p.area, -1, p.rtime, -1,-1,-1,-1,-1,-1))
                i = i+1
                
        out_stream.close()

def open_fsa( args, _params ):
    """ open FSA file(s) and prepare fsa instances
        requires: args.file, args.panel, args.panelfile
    """

    from fatools.lib.fileio.models import Marker, Panel, FSA

    if not args.panel:
        cexit('ERR: using FSA file(s) requires --panel argument!')

    if not args.panelfile:
        cerr('WARN: using default built-in panels')
        Panel.upload(params.default_panels)
    else:
        with open(args.panelfile) as f:
            # open a YAML file that describe panel sets
            Panel.upload(yaml.load(f))

    if not args.markerfile:
        Marker.upload(params.default_markers)
    else:
        raise NotImplementedError()

    panel = Panel.get_panel(args.panel)
    fsa_list = []
    index = 1

    # prepare caching
    if args.use_cache:
        if not os.path.exists('.fatools_caches/channels'):
            os.makedirs('.fatools_caches/channels')

    if args.file:
        for fsa_filename in args.file.split(','):
            fsa_filename = fsa_filename.strip()

            if args.indir != "":
                filename = args.indir + "/" + fsa_filename
            else:
                filename = fsa_filename

            fsa = FSA.from_file(filename, panel, _params, cache = not args.no_cache)
            # yield (fsa, str(i))
            fsa_list.append( (fsa, str(index)) )
            index += 1

    elif args.infile:

        with open(args.infile) as f:
            buf, delim = detect_buffer( f.read() )
        inrows = csv.DictReader( StringIO(buf), delimiter=delim )
        line = 1
        index = 1

        for r in inrows:

            line += 1

            fsa_filename = r['FILENAME'].strip()
            if fsa_filename.startswith('#'):
                continue

            if r.get('OPTIONS', None):
                options = tokenize( r['OPTIONS'] )
            else:
                options = None

            panel_code = r.get('PANEL', None) or args.panel
            panel = Panel.get_panel(panel_code)

            fsa = FSA.from_file( fsa_filename, panel, _params, options, cache = not args.no_cache )
            if 'SAMPLE' in inrows.fieldnames:

                # yield (fsa, r['SAMPLE'])
                fsa_list.append( (fsa, r['SAMPLE']) )
            else:

                # yield (fsa, str(index))
                fsa_list.append( (fsa, str(index)) )
                index += 1

    elif args.indir:
        import glob
        for fsa_filename in glob.glob(args.indir+"/*.fsa"):

            fsa_filename = fsa_filename.strip()

            fsa = FSA.from_file(fsa_filename, panel, _params, cache = not args.no_cache)
            # yield (fsa, str(i))
            fsa_list.append( (fsa, str(index)) )
            index += 1

    return fsa_list


def get_fsa_list( args, dbh ):
    """
    get fsa instance from database based on parameters in args
    """

    if not args.batch:
        cexit('ERR: using database requires --batch argument!', 1)

    batch = dbh.get_batch( args.batch )
    if not batch:
        cexit('ERR: batch %s not found!' % args.batch, 1)

    samples = []
    if args.sample:
        samples = args.sample.split(',')

    fsas = []
    if args.fsa:
        fsas = args.assay.split(',')

    panels = []
    if args.panel:
        panels = args.panel.split(',')

    markers = []
    if args.marker:
        markers = dbh.get_markers(args.panel.split(','))

    fsa_list = []
    for sample in batch.samples:
        if samples and sample.code not in samples: continue
        for assay in sample.assays:
            if assays and assay.filename not in assays: continue
            if panels and assay.panel.code not in panels: continue
            fsa_list.append( (assay, sample.code) )

    cerr('I: number of assays to be processed: %d' % len(assay_list))
    return fsa_list
