#!/usr/bin/python

from __future__ import print_function
import os
import sys

sys.path.append(os.getcwd())

import shutil
import textwrap
import argparse
import itertools
import timeit
import time
import multiprocessing
import numpy as np
from joblib import Parallel, delayed
from subprocess import call
from util import *

###############################################################################
# Parse arguments
###############################################################################
start = timeit.default_timer()

num_cores = multiprocessing.cpu_count()

parser = argparse.ArgumentParser()

mode_opts = ["vcf", "agg", "txt"]
parser.add_argument("-M", "--mode",
                    help="Mode for parsing input. Must be one of \
                        {"+", ".join(mode_opts)+ "}",
                    nargs='?',
                    type=str,
                    choices=mode_opts,
                    metavar='',
                    default="vcf")

parser.add_argument("-i", "--input",
                    help="In VCF mode (default) input file is a VCF \
                        or text file containing paths of multiple VCFs. \
                        Can accept input from STDIN  with \"--input -\". \
                        In aggregation mode, input file is a text file \
                        containing mutation subtype count matrices, \
                        or paths of multiple such matrices. \
                        In plain text mode, input file is tab-delimited text \
                        file containing 5 columns: CHR, POS, REF, ALT, ID",
                    required=True,
                    nargs='?',
                    type=str,
                    # metavar='',
                    default=sys.stdin)

parser.add_argument("-f", "--fastafile",
                    help="reference fasta file",
                    nargs='?',
                    type=str,
                    metavar='',
                    default="chr20.fasta.gz")

parser.add_argument("-s", "--samplefile",
                    help="file with sample IDs to include (one per line)",
                    nargs='?',
                    metavar='',
                    type=str)

parser.add_argument("-g", "--groupfile",
                    help="two-column tab-delimited file containing sample IDs \
                        (column 1) and group membership (column 2) for pooled \
                        analysis",
                    nargs='?',
                    metavar='',
                    type=str)

parser.add_argument("-p", "--projectdir",
                    help="directory to store output files \
                        (do NOT include a trailing '/')",
                    nargs='?',
                    type=str,
                    metavar='',
                    default="doomsayer_output")

parser.add_argument("-m", "--matrixname",
                    help="custom filename for M matrix [without extension]",
                    nargs='?',
                    type=str,
                    metavar='',
                    default="NMF_M_spectra")

parser.add_argument("-o", "--filterout",
                    help="in VCF or plain text modes, re-reads input \
                        file and writes to STDOUT, omitting records that occur \
                        in the detected outliers. To write to a new file, use \
                        standard output redirection [ > out.vcf] at the end of \
                        the doomsayer.py command",
                    action="store_true")

parser.add_argument("-a", "--allsamples",
                    help="disables generation of keep/drop lists. \
                        Forces NMF to run on the entire sample",
                    action="store_true")

parser.add_argument("-R", "--report",
                    help="automatically generates an HTML-formatted report in \
                        R.",
                    action="store_true")

template_opts = ["diagnostics", "msa"]

parser.add_argument("-T", "--template",
                    help="Template for diagnostic report. Must be one of \
                        {"+", ".join(template_opts)+"}",
                    nargs='?',
                    type=str,
                    choices=template_opts,
                    metavar='',
                    default="diagnostics")

filtermode_opts = ["fold", "sd", "chisq"]

parser.add_argument("-F", "--filtermode",
                    help="Method for detecting outliers. Must be one of \
                        {"+", ".join(filtermode_opts)+"}",
                    nargs='?',
                    type=str,
                    choices=filtermode_opts,
                    metavar='',
                    default="fold")

parser.add_argument("-C", "--minsnvs",
                    help="minimum # of SNVs per individual to be included \
                        in analysis",
                    nargs='?',
                    type=int,
                    metavar='',
                    default=0)

parser.add_argument("-X", "--maxac",
                    help="maximum allele count for SNVs to keep in analysis. \
                        Set to 0 to include all variants.",
                    nargs='?',
                    type=int,
                    metavar='',
                    default=1)

parser.add_argument("-t", "--threshold",
                    help="threshold for fold-difference RMSE cutoff, used to \
                        determine which samples are outliers. Must be a \
                        real-valued number > 1. The default is 2. \
                        higher values are more stringent",
                    nargs='?',
                    type=restricted_float,
                    metavar='',
                    default=2)

rank_opts = range(2,11)
ro_str = str(min(rank_opts)) + " and " + str(max(rank_opts))
parser.add_argument("-r", "--rank",
                    help="Rank for NMF decomposition. Must be an integer \
                        between " + ro_str,
                    nargs='?',
                    type=int,
                    choices=rank_opts,
                    metavar='',
                    default=0)

motif_length_opts = [1,3,5,7]
mlo_str = ",".join(str(x) for x in motif_length_opts)

parser.add_argument("-l", "--length",
                    help="motif length. Allowed values are " + mlo_str,
                    nargs='?',
                    type=int,
                    choices=motif_length_opts,
                    metavar='',
                    default=3)

parser.add_argument("-c", "--cpus",
                    help="number of CPUs. Must be integer value between 1 \
                        and "+str(num_cores),
                    nargs='?',
                    type=int,
                    choices=range(1,num_cores+1),
                    metavar='',
                    default=1)

parser.add_argument("-v", "--verbose",
                    help="Enable verbose logging",
                    action="store_true")

args = parser.parse_args()

###############################################################################
# Initialize project directory
###############################################################################
projdir = os.path.realpath(args.projectdir)

if not os.path.exists(args.projectdir):
    if args.verbose:
        eprint("Creating output directory:", projdir)
    os.makedirs(args.projectdir)
else:
    if args.verbose:
        eprint(projdir, "already exists")

if args.verbose:
    eprint("All output files will be located in ", projdir)

###############################################################################
# index subtypes
###############################################################################
eprint("indexing subtypes...") if args.verbose else None
subtypes_dict = indexSubtypes(args.length)

###############################################################################
# Build M matrix from inputs
###############################################################################
if args.mode == "vcf":
    # fasta_dict = SeqIO.to_dict(SeqIO.parse(args.fastafile, "fasta"))
    if(args.input.lower().endswith(('.vcf', '.vcf.gz', '.bcf')) or
            args.input == "-"):
        par = False
        data = processVCF(args, args.input, subtypes_dict, par)
        M = data.M
        samples = data.samples

    elif(args.input.lower().endswith(('.txt'))):
        par = True
        with open(args.input) as f:
            vcf_list = f.read().splitlines()

        results = Parallel(n_jobs=args.cpus) \
            (delayed(processVCF)(args, vcf, subtypes_dict, par) \
            for vcf in vcf_list)

        nrow, ncol = results[1].shape
        M = np.zeros((nrow, ncol))

        for M_sub in results:
            M = np.add(M, M_sub)
        samples = getSamplesVCF(args, vcf_list[1])

elif args.mode == "agg":
    data = aggregateM(args.input, subtypes_dict)
    M = data.M
    samples = data.samples

elif args.mode == "txt":
    data = processTxt(args, subtypes_dict)
    M = data.M
    samples = data.samples

###############################################################################
# Write out M matrix if preparing for aggregation mode
###############################################################################
if args.matrixname != "NMF_M_spectra":
    eprint(textwrap.dedent("""\
            You are running with the --matrixname option. Keep and drop lists
            will not be generated.
            """))
    if args.verbose:
        eprint("Saving M matrix (spectra counts) to:", args.matrixname)

    M_path = projdir + "/" + args.matrixname + ".txt"
    writeM(M, M_path, subtypes_dict, samples)

else:
    # M_f is the relative contribution of each subtype per sample
    M_f = M/(M.sum(axis=1)+1e-8)[:,None]

    # M_err is N x K matrix of residual error profiles, used for RMSE calc
    M_err = np.subtract(M_f, np.mean(M_f, axis=0))
    M_rmse = np.sqrt(np.sum(np.square(M_err), axis=1)/M_err.shape[1])

    eprint("Writing M matrix and RMSE per sample") if args.verbose else None
    M_path = projdir + "/" + args.matrixname + ".txt"
    writeM(M, M_path, subtypes_dict, samples)

    M_path_rates = projdir + "/NMF_M_spectra_rates.txt"
    writeM(M_f, M_path_rates, subtypes_dict, samples)

    rmse_path = projdir + "/doomsayer_rmse.txt"
    writeRMSE(M_rmse, rmse_path, samples)

    if args.allsamples:
        if args.verbose:
            eprint("Using all samples--\
                keep and drop lists will not be generated")
        M_run = M_f
        samples = samples
    else:
        eprint("Generating keep and drop lists") if args.verbose else None
        kd_lists = detectOutliers(M, samples,
            args.filtermode, args.threshold, args.minsnvs)

        keep_samples = kd_lists.keep_samples
        drop_samples = kd_lists.drop_samples
        lowsnv_samples = kd_lists.lowsnv_samples
        drop_indices = kd_lists.drop_indices

        keep_path = projdir + "/doomsayer_keep.txt"
        keeps = open(keep_path, "w")
        for sample in keep_samples:
            keeps.write("%s\n" % sample)
        keeps.close()

        drop_path = projdir + "/doomsayer_drop.txt"
        drops = open(drop_path, "w")
        for sample in drop_samples:
            drops.write("%s\n" % sample)
        drops.close()

        if args.minsnvs > 0:
            lowsnv_path = projdir + \
                "/doomsayer_snvs_lt" + str(args.minsnvs) + ".txt"
            lowsnvs = open(lowsnv_path, "w")
            for sample in lowsnv_samples:
                lowsnvs.write("%s\n" % sample)
            lowsnvs.close()

        if len(drop_samples) > 0:
            if args.verbose:
                eprint(len(drop_samples), "potential outliers found.")

            M_run = M_f[np.array(drop_indices)]
            samples = drop_samples
        else:
            eprint("No outliers detected! NMF will be run on all samples")
            M_run = M_f

    eprint("Running NMF model") if args.verbose else None
    NMFdata = NMFRun(M_run, args, projdir, samples, subtypes_dict)

    # W matrix (contributions)
    W_path = projdir + "/NMF_W_sig_contribs.txt"
    writeW(NMFdata.W, W_path, samples)

    # H matrix (loadings)
    H_path = projdir + "/NMF_H_sig_loads.txt"
    writeH(NMFdata.H, H_path, subtypes_dict)

    yaml = open(projdir + "/config.yaml","w+")
    print("# Config file for doomsayer_diagnostics.r", file=yaml)
    print("keep_path: " + projdir + "/doomsayer_keep.txt", file=yaml)
    print("drop_path: " + projdir + "/doomsayer_drop.txt", file=yaml)
    print("M_path: " + M_path, file=yaml)
    print("M_path_rates: " + M_path_rates, file=yaml)
    print("W_path: " + W_path, file=yaml)
    print("H_path: " + H_path, file=yaml)
    print("RMSE_path: " + rmse_path, file=yaml)
    yaml.close()

###############################################################################
# write output
###############################################################################
if args.filterout:
    if(args.mode == "vcf" and not(args.input.lower().endswith(('.txt')))):
        eprint("Filtering input by drop list...") if args.verbose else None
        filterVCF(args.input, keep_samples)

    elif args.mode =="txt":
        eprint("Filtering input by drop list...") if args.verbose else None
        filterTXT(args.input, keep_samples)

    else:
        eprint("Input not compatible with auto-filtering function")

###############################################################################
# auto-generate diagnostic report in R
###############################################################################
if(args.report and args.matrixname == "NMF_M_spectra"):

    template_src = sys.path[0] + "/report_templates/" + args.template + ".Rmd"
    template_dest = projdir + "/report.Rmd"
    shutil.copy(template_src, template_dest)

    cmd = "Rscript --vanilla generate_report.r " + projdir + "/config.yaml"
    if args.verbose:
        eprint("Rscript will run the following command:")
        eprint(cmd)
    call(cmd, shell=True)

stop = timeit.default_timer()
tottime = round(stop - start, 2)
eprint("Total runtime:", tottime, "seconds") if args.verbose else None
