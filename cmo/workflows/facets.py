import cmo
from cmo import workflow
from abc import ABCMeta
import argparse, os, sys
from distutils.version import StrictVersion
#WHOA, existentially troubling, man
PYTHON = cmo.util.programs['python']['default']


##all workflows can be a subclass of this class to help new workflows get written
class Schematic(object):
  #  @abstractmethod
    def construct_workflow(self):
        pass
 #   @abstractmethod
    def parse_workflow_args(self):
        pass
  #  @abstractmethod
    def check_inputs(self):
        pass

class Facets(Schematic):
    """ Facets workflow
    {'force': False, 
    'vcf': None, 
    'tumor_name': None,
    'normal_name': None,
    'tumor_bam': '/home/jonssonp/res/tgen/impact/HU910259-T.bam',
    'workflow_mode': 'LSF',
    'tag': None,
    'normal_bam': '/home/jonssonp/res/tgen/impact/HU910259-N.bam',
    'output_dir': '/ifs/work/charris/facets_test_tgen_052'}
    """
    

    ##all workflows have this method that takes in a dict. we can put the required information of the dict in the python doc like above
    def construct_workflow(self, args, facets_args):
        vcf = args['vcf']
        force = args['force']
        tumor_sample = args['tumor_name']
        normal_sample = args['normal_name']
        tumorbam = os.path.abspath(args['tumor_bam'])
        normalbam = os.path.abspath(args['normal_bam'])
        tag = args['tag']
        rlib_parse = argparse.ArgumentParser()
        rlib_parse.add_argument("-r", "--R_lib")
        rlib_arg, _ = rlib_parse.parse_known_args(facets_args)
        try:
            output_dir = os.path.abspath(args['output_dir'])
        except:
            output_dir = None
        snps = None
        #use user snps file instead of one we ahve stored for the genome we find in the bam
        if vcf:
            snps = os.path.abspath(vcf)
        if not rlib_arg.R_lib:
            rlib_arg="0.3.9"
        else:
            rlib_arg=rlib_arg.R_lib
        #look at @RG SM: tag for samples
        if not tumor_sample: 
            tumor_sample = cmo.util.infer_sample_from_bam(tumorbam)
        if not normal_sample:
            normal_sample = cmo.util.infer_sample_from_bam(normalbam)
        if normal_sample == tumor_sample:
            print >>sys.stderr, "Sample names in normal and tumor are the same- forcibly override one or both to use this pipeline"
            sys.exit(1)
        if not tag and tumor_sample and normal_sample:  
            tag = tumor_sample + "__" + normal_sample
        elif not tumor_sample:
            print >>sys.stderr, "Can't infer tumor sample name from BAM file-- please supply it to workflow"
            sys.exit(1)
        elif not normal_sample:
            print >>sys.stderr, "Can't infer normal sample name from BAM file-- please supply it to workflow"
            sys.exit(1)
        default_basecount_options = [ "--sort_output", "--compress_output", "--filter_improper_pair 0"]
        if not output_dir:
            #TODO make directory safe for invalid dir chars in sample names
            output_dir = os.path.join(os.getcwd(), tag, '')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        #if the idiot user supplied relative path we must fix
        output_dir = os.path.abspath(output_dir)
        
        #count jobs
        count_jobs = []
        tumor_normal_counts = []

        merge_job = None
        if not os.path.exists(os.path.abspath(tumorbam)):
            print >>sys.stderr, "Tumor bam does not exist? is %s a real path to a bam? " % tumorbam
        if not os.path.exists(os.path.abspath(normalbam)):
            print >>sys.stderr, "Normal bam does not exist? is %s a real path to a bam? " % normalbam
        print rlib_arg
        temp_bams = list()
        if(rlib_arg != None and StrictVersion(rlib_arg) < StrictVersion("0.5.2")):
            for (bam, base) in [(tumorbam, tumor_sample), (normalbam, normal_sample)]:
                out_file = os.path.abspath(os.path.join(output_dir, base + ".dat"))
                if os.path.exists(out_file + ".gz") and not force:
                    #pretend we did this shitty slow step
                    tumor_normal_counts.append(out_file)
                    continue
                #first we add tumor, then normal - the order mergeTN expects them
                tumor_normal_counts.append(out_file)
                basecount_cmd = ["cmo_getbasecounts", "--bam", bam, "--out", out_file] + default_basecount_options
                if(snps):
                    basecount_cmd = basecount_cmd + ["--vcf" ,os.path.abspath(snps)]
                #print " ".join(basecount_cmd)
                job = workflow.Job(" ".join(basecount_cmd), resources="rusage[mem=40]", name="getBasecounts " + base)
                count_jobs.append(job)
        else:
            for (bam, base) in [(tumorbam, tumor_sample), (normalbam, normal_sample)]:
                out_file = os.path.abspath(os.path.join(output_dir, base + ".ppfixed.bam"))
                if not os.path.exists(out_file):
                    temp_bams.append(out_file)
                    ppfix_cmd = [cmo.util.programs['ppflag-fixer']['default'], bam, out_file]
                    count_jobs.append(workflow.Job(" ".join(ppfix_cmd), name="ppflag-fixer"))
            if not snps:
                (genome, fasta) = cmo.util.infer_fasta_from_bam(tumorbam)
                snps = cmo.util.genomes[genome]['facets_snps']
            merged_counts = os.path.join(output_dir, "countsMerged____" + tag + ".dat.gz")
            if not os.path.exists(merged_counts):
                basecount_cmd = [cmo.util.programs['snp-pileup']['default'], 
                        "-A", "-g", 
                        "--pseudo-snps=50",
                        snps,
                        merged_counts,
                        normalbam,
                        tumorbam]
                merge_job = workflow.Job(" ".join(basecount_cmd), resources="rusage[mem=40]", name="snp-pileup " + tag)
       
        merged_counts = os.path.join(output_dir, "countsMerged____" + tag + ".dat.gz")

        #don't need to merge for new facets snp-pileup, don't do dis
        if(rlib_arg != None and StrictVersion(rlib_arg) < StrictVersion("0.5.2")):
            if not os.path.exists(merged_counts):
                merge_cmd = ["cmo_facets mergeTN", "-t",  tumor_normal_counts[0], "-n", tumor_normal_counts[1], "-o", merged_counts]
                #print " ".join(merge_cmd)
                merge_job = workflow.Job(" ".join(merge_cmd), resources="rusage[mem=60]", name="mergeTN " + tag)

          
        #facets job
        #args will be [--foo, value] or [-f, value] in this list
        facets_dir = "facets_"
        if not facets_args or len(facets_args) ==0:
            facets_args = []
            facets_dir += "default"
        else:
            it = iter(facets_args)
            for val in it:
                arg = val.lstrip("-")[0]
                value = next(it)
                facets_dir += "%s-%s" % (arg, value)
        facets_dir = os.path.join(output_dir, cmo.util.filesafe_string(facets_dir))
        if os.path.exists(facets_dir) and not force:
            print >>sys.stderr, "This facets setting directory already exists- bailing out - RM it to force rerun"
            sys.exit(1)
        else:
            print >>sys.stderr, "created facets subdir for these settings: %s" % facets_dir
            if not os.path.exists(facets_dir):
                os.makedirs(facets_dir)
            else:
                shutil.rmtree(facets_dir)
                os.makedirs(facets_dir)
        if not rlib_arg:
            facets_cmd = ["cmo_facets", "--lib-version=0.3.9", "doFacets", "-f", merged_counts, "-t", tag, "-D", facets_dir] + facets_args
        else:
            facets_cmd = ["cmo_facets", "--lib-version", rlib_arg, "doFacets", "-f", merged_counts, "-t", tag, "-D", facets_dir] + facets_args
        facets_job = workflow.Job(" ".join(facets_cmd), est_wait_Time="59", name="Run Facets")
        dependencies = {}
      
      #FIXME: can we have a merge exist without the counts file?
        #if so this set of ifs needs to be redone
        jobs = []
        #connect snp-pileup directly to facets if > "0.5.2"
    #    if(rlib_arg != None and StrictVersion(rlib_arg) < StrictVersion("0.5.2")):
        #if this ran once and there is a merge but not bams anymore
        #don't schedule either the bams or the merge
        if len(count_jobs) > 0 and merge_job:
            dependencies[count_jobs[0]]=[merge_job]
            dependencies[count_jobs[1]]=[merge_job]
            jobs = jobs + count_jobs
        if(merge_job):
            dependencies[merge_job]=[facets_job]
            jobs.append(merge_job)
    #    else: 
    #        if len(count_jobs) > 0:
                #there should be only one count_job for > "0.5.2"
    #            dependencies[count_jobs[0]]=facets_job
    #            jobs.append(count_jobs[0])
        if(rlib_arg != None and StrictVersion(rlib_arg) >= StrictVersion("0.5.2")):
            rm_cmd = ["rm","-f"]  + temp_bams
            rm_job = workflow.Job(" ".join(rm_cmd), name="Remove temp bams")
            jobs.append(rm_job)
            dependencies[facets_job]=rm_job
        #make workflow
        jobs.append(facets_job)
        return {"jobs":jobs, "dependencies":dependencies, "workflow_name":" ".join(["Facets", tag]), "terminal_jobs": facets_job, "initial_jobs":count_jobs}
    #all workflows contain enough knowledge to launch themselves at the command line in the form of an argument parse object
    #the launcher turns it into a dictionary, so the "construct_workflow" method does not need to parse an ArgumentParse object
    #so that chaining workflows becomes as easy as putting dicts together, rather than faking ArgParse objects
    def parse_workflow_args(self, parent=None):
        if not parent:
            parser = argparse.ArgumentParser(description="Run Facets on luna!", epilog="Include any FACETS args directly on this command line and they will be passed through")
        else:
            parser = argparse.ArgumentParser(description="Run Facets on luna!", epilog="Include any FACETS args directly on this command line and they will be passed through", parents=[parent])
        parser.add_argument("--normal-bam", required=True, help="The normal bam file")
        parser.add_argument("--tumor-bam", required=True, help="The Tumor bam file")
        parser.add_argument("--tag", help="The optional tag with which to identify this pairing, default TUMOR_SAMPLE__NORMAL_SAMPLE")
        parser.add_argument("--vcf", help="override default FACETS snp positions")
        parser.add_argument("--output-dir", help="output dir, will default to $CWD/TAG_NAME/")
        parser.add_argument("--normal-name", help="Override this if you don't want to use the SM: tag on the @RG tags within the bam you supply-- required if your bam doesn't have well formatted @RG SM: tags")
        parser.add_argument("--tumor-name", help="Override this if you don't want to use the SM: tag on the @RG tags in the tumor bam you supply-- required if your bam doesnt have well formatted @RG SM: tags")
        parser.add_argument("--force", action="store_true", help="forcibly overwrite any directories you find there")
        return parser



if __name__=='__main__':
    facets = Facets()
    parser = facets.parse_workflow_args();
    results_dict = facets.construct_workflow(vars(parser))
    facets_workflow = workflow.Workflow(results_dict['jobs'], results_dict['dependencies'], name=results_dict['workflow_name'])
    facets_workflow.run(args.workflow_mode)
         


