# v13 - added checking of heterodimer formation of primers
# v14 - added ability to read and write to gzipped files; speed of processing was increased 10-times
# v15 - added ability to write untrimmed and trimmed reads to one file. Also added possibility that 3'-primer may be absent
# v16 - added ability to trim on the 3'-end only part of primer sequence

# Section of importing modules
import sys
from Bio import SeqIO
from Bio.Seq import Seq
from Bio import pairwise2
import glob,gzip
import regex
import time
from multiprocessing import Pool,Queue
import argparse
import time,math
from itertools import repeat
from operator import itemgetter
import hashlib

def makeHashes(seq,k):
    # k is the length of parts
    subSeqs=[]
    h=[]
    lens=set([k])
    for i in range(len(seq)-k+1):
        h.append(hashlib.md5(seq[i:i+k].encode('utf-8')).hexdigest())
    return(h,lens)

def initializer(maxPrimerLen2,primerLocBuf2,errNumber2,primersR1_52,primersR1_32,primersR2_52,primersR2_32,
                primerR1_5_hashes2,primerR1_5_hashLens2,primerR2_5_hashes2,primerR2_5_hashLens2,
                primersFileR1_32,primersFileR2_52,primersFileR2_32,readsFileR22,primersStatistics2,idimer2,primer3absent2,minPrimer3Len2):
    global primersR1_5,primersR1_3,primersR2_5,primersR2_3,primersFileR1_3,primersFileR2_3,primersFileR2_5,readsFileR2
    global trimmedReadsR1,trimmedReadsR2,untrimmedReadsR1,untrimmedReadsR2
    global maxPrimerLen,q4,errNumber,primerLocBuf,readsPrimerNum,primersStatistics
    global primerR1_5_hashes,primerR2_5_hashes,primerR1_5_hashLens,primerR2_5_hashLens,primer3absent,idimer
    maxPrimerLen=maxPrimerLen2
    primerLocBuf=primerLocBuf2
    errNumber=errNumber2
    primersR1_5=primersR1_52
    primersR1_3=primersR1_32
    primersR2_5=primersR2_52
    primersR2_3=primersR2_32
    primerR1_5_hashes=primerR1_5_hashes2; primerR1_5_hashLens=primerR1_5_hashLens2;
    primerR2_5_hashes=primerR2_5_hashes2; primerR2_5_hashLens=primerR2_5_hashLens2
    primersFileR1_3=primersFileR1_32
    primersFileR2_5=primersFileR2_52
    primersFileR2_3=primersFileR2_32
    readsFileR2=readsFileR22
    primersStatistics=primersStatistics2
    idimer=idimer2
    primer3absent=primer3absent2
    minPrimer3Len=minPrimer3Len2

# Section of functions
def showPercWork(done,allWork):
    percDoneWork=round((done/allWork)*100,2)
    sys.stdout.write("\r"+str(percDoneWork)+"%")
    sys.stdout.flush()

def revComplement(nuc):
    return(str(Seq(nuc).reverse_complement()))

def countDifs(s1,s2):
    a=pairwise2.align.globalms(s1,s2,2,-1,-1.53,0)
    maxSum=0
    k=0
    for i,b in enumerate(a):
        left=len(b[1])-len(b[1].lstrip('-'))+len(b[0])-len(b[0].lstrip('-'))
        right=len(b[1])-len(b[1].rstrip('-'))+len(b[0])-len(b[0].rstrip('-'))
        if left+right>maxSum:
            maxSum=left+right
            k=i
    ins=a[k][1].strip('-').count('-')
    dels=a[k][0].strip('-').count('-')
    left=max(len(a[k][1])-len(a[k][1].lstrip('-')),len(a[k][0])-len(a[k][0].lstrip('-')))
    right=max(len(a[k][1])-len(a[k][1].rstrip('-')),len(a[k][0])-len(a[k][0].rstrip('-')))
    if right==0:
        mism=sum(b!=c and c!='-' and b!='-' for b,c in zip(a[k][0][left:],a[k][1][left:]))
        return((mism,ins,dels,a[k][0][left:]))
    else:
        mism=sum(b!=c and c!='-' and b!='-' for b,c in zip(a[k][0][left:-right],a[k][1][left:-right]))
        return((mism,ins,dels,a[k][0][left:-right]))

def getErrors(s1,s2):
    # This function calculates number of errors between designed and sequenced primer sequences
    # s1 - initial sequence of primer
    # s2 - sequenced sequece of primer
    # Align them
    a=pairwise2.align.localms(s1,s2,2,-1,-1.53,0)
    maxSum=0
    k=0
    # First of all we detect the best alignment
    # and coordinates in range of which we will get mutations
    for i,b in enumerate(a):
        left=len(b[1])-len(b[1].lstrip('-'))+len(b[0])-len(b[0].lstrip('-'))
        right=len(b[1])-len(b[1].rstrip('-'))+len(b[0])-len(b[0].rstrip('-'))
        if left+right>maxSum:
            maxSum=left+right
            k=i
    poses=[] # poses - list of positions in sequences with mutations
    muts=[] # muts - mutations
    if right==0:
        s3=a[k][0][left:]
        s4=a[k][1][left:]
    else:
        s3=a[k][0][left:-right]
        s4=a[k][1][left:-right]
    for i,(b,c) in enumerate(zip(s3,s4)):
        if b!=c:
            poses.append(i+left+1)
            muts.append(b+'/'+c)
    return(poses,muts)

def trimPrimers(data):
    # This function get two records from both read files (R1 and R2)
    # and trim them
    # As a result it returns list
    #[trimmedReads,untrimmedReads]
    # resList is a variable with trimmed read sequences (0) and untrimmed read sequences (1)
    resList=[[None,None],[None,None]]
    r1,r2=data
    # Find primer at the 5'-end of R1 read
    readHashes=set()
    for l in primerR1_5_hashLens:
        hashes,lens=makeHashes(str(r1.seq[:maxPrimerLen+primerLocBuf]),l)
        readHashes.update(hashes)
    matchedPrimers={}
    for rh in readHashes:
        if rh in primerR1_5_hashes.keys():
            for a in primerR1_5_hashes[rh]:
                if a not in matchedPrimers.keys():
                    matchedPrimers[a]=1
                else:
                    matchedPrimers[a]+=1
    bestPrimer=None
    bestPrimerValue=None
    goodPrimers=[]
    goodPrimerNums=[]
    for key,item in sorted(matchedPrimers.items(),key=itemgetter(1),reverse=True):
        if bestPrimer==None:
            bestPrimer=key
            bestPrimerValue=item
            continue
        if item>=bestPrimerValue-1:
            goodPrimers.append(primersR1_5[key])
            goodPrimerNums.append(key)
        else: break
    if bestPrimer!=None:
        m1=regex.search(r''+primersR1_5[bestPrimer]+'{e<='+errNumber+'}',str(r1.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
    else:
        return([[None,None],[r1,r2]],[],False)
##    m1=regex.search(r'(?:'+'|'.join(primersR1_5)+'){e<='+errNumber+'}',str(r1.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
    # Use result of searching 5'-primer
    if m1==None:
        if len(goodPrimers)>0:
            m1=regex.search(r'(?:'+'|'.join(goodPrimers)+'){e<='+errNumber+'}',str(r1.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
            if m1==None:
                # Save this pair of reads to untrimmed sequences
                return([[None,None],[r1,r2]],[],False)
            else:
                primerNum=goodPrimerNums[list(m1.groups()).index(m1[0])]
        else:
            return([[None,None],[r1,r2]],[],False)
    else:
        primerNum=bestPrimer
    # Find primer at the 5'-end of R2 read
    if primersFileR2_5:
        m3=regex.search(r'(?:'+primersR2_5[primerNum]+'){e<='+errNumber+'}',str(r2.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
        if m3==None:
            # If user wants to identify hetero- and homodimers of primers
            if idimer:
                readHashes=set()
                for l in primerR2_5_hashLens:
                    hashes,lens=makeHashes(str(r2.seq[:maxPrimerLen+primerLocBuf]),l)
                    readHashes.update(hashes)
                matchedPrimers={}
                for rh in readHashes:
                    if rh in primerR2_5_hashes.keys():
                        for a in primerR2_5_hashes[rh]:
                            if a not in matchedPrimers.keys():
                                matchedPrimers[a]=1
                            else:
                                matchedPrimers[a]+=1
                bestPrimer=None
                bestPrimerValue=None
                goodPrimers=[]
                goodPrimerNums=[]
                for key,item in sorted(matchedPrimers.items(),key=itemgetter(1),reverse=True):
                    if bestPrimer==None:
                        bestPrimer=key
                        bestPrimerValue=item
                        continue
                    if item>=bestPrimerValue-1:
                        goodPrimers.append(primersR2_5[key])
                        goodPrimerNums.append(key)
                    else: break
                if bestPrimer!=None:
                    m3=regex.search(r''+primersR2_5[bestPrimer]+'{e<='+errNumber+'}',str(r2.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
                else:
                    return([[None,None],[r1,r2]],[],False)
##                    m3=regex.search(r'(?:'+'|'.join(primersR2_5)+'){e<='+errNumber+'}',str(r2.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
                # Use result of searching 5'-primer
                if m3==None:
                    if len(goodPrimers)>0:
                        m3=regex.search(r'(?:'+'|'.join(goodPrimers)+'){e<='+errNumber+'}',str(r2.seq[:maxPrimerLen+primerLocBuf]),flags=regex.BESTMATCH)
                        if m3==None:
                            # Save this pair of reads to untrimmed sequences
                            return([[None,None],[r1,r2]],[],False)
                        else:
                            primerNum2=goodPrimerNums[list(m3.groups()).index(m3[0])]
                    else:
                        return([[None,None],[r1,r2]],[],False)
                else:
                    primerNum2=bestPrimer
                # If we found two different 
                if primerNum!=primerNum2:
                    return([[None,None],[r1,r2]],[],[primerNum,primerNum2])
            else:
                # Save this pair of reads to untrimmed sequences
                return([[None,None],[r1,r2]],[],False)
        else:
            primerNum2=primerNum
    # Find primer at the 3'-end of R1 read
    if primersFileR1_3:
        if not minPrimer3Len:
            m2=regex.search(r'(?:'+primersR1_3[primerNum]+'){e<='+errNumber+'}',str(r1.seq[-maxPrimerLen-primerLocBuf:]),flags=regex.BESTMATCH)
        else:
            errNumberDescreased=int(round(int(errNumber)*minPrimer3Len/len(primersR1_3[primerNum][:-2])))
            m2=regex.search(r'(?:'+primersR1_3[primerNum][:minPrimer3Len]+')){e<='+str(errNumberDescreased)+'}',str(r1.seq[-maxPrimerLen-primerLocBuf:]),flags=regex.BESTMATCH)
        if not primer3absent and m2==None:
            # Save this pair of reads to untrimmed sequences
            return([[None,None],[r1,r2]],[],[primerNum,primerNum2])
    # Find primer at the 3'-end of R2 read
    if primersFileR2_3:
        if not minPrimer3Len:
            m4=regex.search(r'(?:'+primersR2_3[primerNum]+'){e<='+errNumber+'}',str(r2.seq[-maxPrimerLen-primerLocBuf:]),flags=regex.BESTMATCH)
        else:
            errNumberDescreased=int(round(int(errNumber)*minPrimer3Len/len(primersR2_3[primerNum][:-2])))
            m4=regex.search(r'(?:'+primersR2_3[primerNum][:minPrimer3Len]+')){e<='+str(errNumberDescreased)+'}',str(r2.seq[-maxPrimerLen-primerLocBuf:]),flags=regex.BESTMATCH)
        if not primer3absent and m4==None:
            # Save this pair of reads to untrimmed sequences
            return([[None,None],[r1,r2]],[],[primerNum,primerNum2])
    # If all primers were found
    # Trim sequences of primers and write them to result file
    if primersFileR1_3 and m2!=None:
        resList[0][0]=r1[m1.span()[1]:len(r1.seq)-maxPrimerLen-primerLocBuf+m2.span()[0]]
    else:
        resList[0][0]=r1[m1.span()[1]:]
    if readsFileR2:
        if primersFileR2_3 and m4!=None:
            resList[0][1]=r2[m3.span()[1]:len(r2.seq)-maxPrimerLen-primerLocBuf+m4.span()[0]]
        elif primersFileR2_5:
            resList[0][1]=r2[m3.span()[1]:]
    # Save number of errors and primers sequences
    # [number of primer,difs1,difs2,difs3,difs4,]
    # Each dif is a set of (# of mismatches,# of insertions,# of deletions,primer_seq)
    if primersStatistics:
        difs1=countDifs(m1[0],primersR1_5[primerNum][1:-1])
        if primersFileR1_3 and m2!=None: difs2=countDifs(m2[0],primersR1_3[primerNum][1:-1])
        else: difs2=(0,0,0,'')
        if primersFileR2_5: difs3=countDifs(m3[0],primersR2_5[primerNum][1:-1])
        else: difs3=(0,0,0,'')
        if primersFileR2_3 and m4!=None: difs4=countDifs(m4[0],primersR2_3[primerNum][1:-1])
        else: difs4=(0,0,0,'')
        return (resList,[primerNum,difs1,difs2,difs3,difs4],False)
    else:
        return (resList,[],False)
    
if __name__ == "__main__":    
    # Section of reading arguments
    par=argparse.ArgumentParser(description='This script cuts primers from reads sequences')
    par.add_argument('--readsFile_r1','-r1',dest='readsFile1',type=str,help='file with R1 reads of one sample',required=True)
    par.add_argument('--readsFile_r2','-r2',dest='readsFile2',type=str,help='file with R2 reads of one sample',required=False)
    par.add_argument('--primersFileR1_5','-pr15',dest='primersFileR1_5',type=str,help='fasta-file with sequences of primers on the 5\'-end of R1 reads',required=True)
    par.add_argument('--primersFileR2_5','-pr25',dest='primersFileR2_5',type=str,help='fasta-file with sequences of primers on the 5\'-end of R2 reads. Do not use this parameter if you have single-end reads',required=False)
    par.add_argument('--primersFileR1_3','-pr13',dest='primersFileR1_3',type=str,help='fasta-file with sequences of primers on the 3\'-end of R1 reads. It is not required. But if it is determined, -pr23 is necessary',required=False)
    par.add_argument('--primersFileR2_3','-pr23',dest='primersFileR2_3',type=str,help='fasta-file with sequences of primers on the 3\'-end of R2 reads',required=False)
    par.add_argument('--trimmedReadsR1','-tr1',dest='trimmedReadsR1',type=str,help='name of file for trimmed R1 reads',required=True)
    par.add_argument('--trimmedReadsR2','-tr2',dest='trimmedReadsR2',type=str,help='name of file for trimmed R2 reads',required=False)
    par.add_argument('--untrimmedReadsR1','-utr1',dest='untrimmedReadsR1',type=str,help='name of file for untrimmed R1 reads. If you want to write reads that has not been trimmed to the same file as trimmed reads, type the same name',required=True)
    par.add_argument('--untrimmedReadsR2','-utr2',dest='untrimmedReadsR2',type=str,help='name of file for untrimmed R2 reads. If you want to write reads that has not been trimmed to the same file as trimmed reads, type the same name',required=False)
    par.add_argument('--primersStatistics','-stat',dest='primersStatistics',type=str,help='name of file for statistics of errors in primers. This works only for paired-end reads with primers at 3\'- and 5\'-ends',required=False)
    par.add_argument('--error-number','-err',dest='errNumber',type=int,help='number of errors (substitutions, insertions, deletions) that allowed during searching primer sequence in a read sequence. Default: 5',default=5)
    par.add_argument('--primer-location-buffer','-plb',dest='primerLocBuf',type=int,help='Buffer of primer location in the read from the start or end of read. If this value is zero, than cutPrimers will search for primer sequence in the region of the longest primer length. Default: 10',default=10)
    par.add_argument('--min-primer3-length','-primer3len',dest='minPrimer3Len',type=int,help="Minimal length of primer on the 3'-end to trim. Use this parameter, if you are ready to trim only part of primer sequence of the 3'-end of read")
    par.add_argument('--primer3-absent','-primer3',dest='primer3absent',action='store_true',help="if primer at the 3'-end may be absent, use this parameter")
    par.add_argument('--identify-dimers','-idimer',dest='idimer',type=str,help='use this parameter if you want to get statistics of homo- and heterodimer formation. Choose file to which statistics of primer-dimers will be written. This parameter may slightly decrease the speed of analysis')
    par.add_argument('--threads','-t',dest='threads',type=int,help='number of threads',default=2)
    args=par.parse_args()
    print('The command was:\n',' '.join(sys.argv))
    readsFileR1=args.readsFile1
    readsFileR2=args.readsFile2
    primersFileR1_5=args.primersFileR1_5
    primersFileR2_5=args.primersFileR2_5
    primersFileR1_3=args.primersFileR1_3
    primersFileR2_3=args.primersFileR2_3
    primer3absent=args.primer3absent
    minPrimer3Len=args.minPrimer3Len
    errNumber=str(args.errNumber)
    primerLocBuf=args.primerLocBuf
    primersStatistics=args.primersStatistics
    idimer=args.idimer
    if (primersFileR1_3 and not primersFileR1_5) or (not primersFileR2_5 and primersFileR2_3):
        print('ERROR: use of -pr13 or -pr23 should be accompanied by use of second one parameter for 5\'-end')
        exit(0)
    if (not readsFileR2 and primersFileR2_5) or (not readsFileR2 and primersFileR2_3):
        print('ERROR: use of -pr23 or -pr25 should be accompanied by use of readsFile2 parameter')
        exit(0)
    if readsFileR2 and not primersFileR2_5:
        print('ERROR: use of -r2 parameter should be accompanied by use of at least -pr25 parameter')
        exit(0)
    try:
        if args.trimmedReadsR1[-3:]!='.gz':
            trimmedReadsR1=open(args.trimmedReadsR1,'w')
        else:
            trimmedReadsR1=gzip.open(args.trimmedReadsR1,'wt')
    except FileNotFoundError:
        print('########')
        print('ERROR! Could not create file:',args.trimmedReadsR1)
        print('########')
        exit(0)
    if args.untrimmedReadsR1==args.trimmedReadsR1:
        untrimmedReadsR1=trimmedReadsR1
    else:
        try:
            if args.untrimmedReadsR1[-3:]!='.gz':
                untrimmedReadsR1=open(args.untrimmedReadsR1,'w')
            else:
                untrimmedReadsR1=gzip.open(args.untrimmedReadsR1,'wt')
        except FileNotFoundError:
            print('########')
            print('ERROR! Could not create file:',args.untrimmedReadsR1)
            print('########')
            exit(0)
    if args.trimmedReadsR2:
        try:
            if args.trimmedReadsR2[-3:]!='.gz':
                trimmedReadsR2=open(args.trimmedReadsR2,'w')
            else:
                trimmedReadsR2=gzip.open(args.trimmedReadsR2,'wt')
        except FileNotFoundError:
            print('########')
            print('ERROR! Could not create file:',args.trimmedReadsR2)
            print('########')
            exit(0)
    if args.untrimmedReadsR2:
        if args.untrimmedReadsR2==args.trimmedReadsR2:
            untrimmedReadsR2=trimmedReadsR2
        else:
            try:
                if args.untrimmedReadsR2[-3:]!='.gz':
                    untrimmedReadsR2=open(args.untrimmedReadsR2,'w')
                else:
                    untrimmedReadsR2=gzip.open(args.untrimmedReadsR2,'wt')
            except FileNotFoundError:
                print('########')
                print('ERROR! Could not create file:',args.untrimmedReadsR2)
                print('########')
                exit(0)
    if idimer and not readsFileR2:
        print('Warning! You did not provide R2-file so parameter "-idimer" will be ignored')
        idimer=None
    if idimer:
        try:
            idimerFile=open(idimer,'w')
        except FileNotFoundError:
            print('########')
            print('ERROR! Could not create file:',idimer)
            print('########')
            exit(0)
        primerDimers={}
    if primersStatistics:
        primersStatistics=open(args.primersStatistics,'w')
        primersStatisticsPos=open(args.primersStatistics[:-4]+'_poses.tab','w')
        primersStatisticsType=open(args.primersStatistics[:-4]+'_types.tab','w')
    threads=int(args.threads)

    # Read fasta-files with sequences of primers
    print('Reading files of primers...')
    lastPrimerNum=0
    # maxPrimerLen - variable that contains length of the longest primer
    maxPrimerLen=0
    # primers in R1 on the 5'-end
    primersR1_5=[]
    primersR1_5_names=[]
    primerR1_5_hashes={}
    primerR1_5_hashLens=set()
    primerR2_5_hashes={}
    primerR2_5_hashLens=set()
    i=0
    try:
        for r in SeqIO.parse(primersFileR1_5,'fasta'):
            primersR1_5_names.append(r.name)
            primersR1_5.append('('+str(r.seq)+')')
            partLens=math.floor(len(r.seq)/(int(errNumber)+1))
            hashes,lens=makeHashes(str(r.seq),partLens)
            primerR1_5_hashLens.update(lens)
            for h in hashes:
                if h in primerR1_5_hashes.keys():
                    primerR1_5_hashes[h].append(i)
                else:
                    primerR1_5_hashes[h]=[i]
            if len(r.seq)>maxPrimerLen:
                maxPrimerLen=len(r.seq)
            i+=1
    except FileNotFoundError:
        print('########')
        print('ERROR! File not found:',primersFileR1_5)
        print('########')
        exit(0)
    # primers in R2 on the 5'-end
    if primersFileR2_5:
        primersR2_5=[]
        primersR2_5_names=[]
        i=0
        try:
            for r in SeqIO.parse(primersFileR2_5,'fasta'):
                primersR2_5_names.append(r.name)
                primersR2_5.append('('+str(r.seq)+')')
                partLens=math.floor(len(r.seq)/(int(errNumber)+1))
                hashes,lens=makeHashes(str(r.seq),partLens)
                primerR2_5_hashLens.update(lens)
                for h in hashes:
                    if h in primerR2_5_hashes.keys():
                        primerR2_5_hashes[h].append(i)
                    else:
                        primerR2_5_hashes[h]=[i]
                if len(r.seq)>maxPrimerLen:
                    maxPrimerLen=len(r.seq)
                i+=1
        except FileNotFoundError:
            print('########')
            print('ERROR! File not found:',primersFileR2_5)
            print('########')
            exit(0)
    else:
        primersR2_5=None
    # primers in R1 on the 3'-end
    if primersFileR1_3:
        primersR1_3=[]
        primersR1_3_names=[]
        try:
            for r in SeqIO.parse(primersFileR1_3,'fasta'):
                primersR1_3_names.append(r.name)
                primersR1_3.append('('+str(r.seq)+')')
                if len(r.seq)>maxPrimerLen:
                    maxPrimerLen=len(r.seq)
        except FileNotFoundError:
            print('########')
            print('ERROR! File not found:',primersFileR1_3)
            print('########')
            exit(0)
    else:
        primersR1_3=None
    # primers in R2 on the 3'-end
    if primersFileR2_3:
        primersR2_3=[]
        primersR2_3_names=[]
        try:
            for r in SeqIO.parse(primersFileR2_3,'fasta'):
                primersR2_3_names.append(r.name)
                primersR2_3.append('('+str(r.seq)+')')
                if len(r.seq)>maxPrimerLen:
                    maxPrimerLen=len(r.seq)
        except FileNotFoundError:
            print('########')
            print('ERROR! File not found:',primersFileR2_3)
            print('########')
            exit(0)
    else:
        primersR2_3=None
    # Read file with R1 and R2 reads
    try:
        if readsFileR1[-3:]!='.gz':
            allWork=open(readsFileR1).read().count('\n')/4
        else:
            allWork=gzip.open(readsFileR1,'rt').read().count('\n')/4
    except FileNotFoundError:
        print('########')
        print('ERROR! Could not open file:',readsFileR1)
        print('########')
        exit(0)
    print('Reading input FASTQ-file(s)...')
    if readsFileR1[-3:]!='.gz':
        data1=SeqIO.parse(readsFileR1,'fastq')
    else:
        data1=SeqIO.parse(gzip.open(readsFileR1,'rt'),'fastq')
    if readsFileR2:
        try:
            if readsFileR2[-3:]!='.gz':
                data2=SeqIO.parse(readsFileR2,'fastq')
            else:
                data2=SeqIO.parse(gzip.open(readsFileR2,'rt'),'fastq')
        except FileNotFoundError:
            print('########')
            print('ERROR! Could not open file:',readsFileR2)
            print('########')
            exit(0)
    else:
        data2=['']*int(allWork)
    # Create Queue for storing result and Pool for multiprocessing
    primerErrorQ=[] 
    p=Pool(threads,initializer,(maxPrimerLen,primerLocBuf,errNumber,primersR1_5,primersR1_3,primersR2_5,primersR2_3,
                                primerR1_5_hashes,primerR1_5_hashLens,primerR2_5_hashes,primerR2_5_hashLens,
                                primersFileR1_3,primersFileR2_5,primersFileR2_3,readsFileR2,primersStatistics,idimer,primer3absent,minPrimer3Len))
    # Cutting primers and writing result immediately
    print('Trimming primers from reads...')
    doneWork=0
    showPercWork(0,allWork)
    for res in p.imap_unordered(trimPrimers,zip(data1,data2),10):
        doneWork+=1
        showPercWork(doneWork,allWork)
        if res[1]!=[]:
            primerErrorQ.append(res[1])
        if readsFileR2:
            if res[0][0][0] is not None and res[0][0][1] is not None:
                SeqIO.write(res[0][0][0],trimmedReadsR1,'fastq')
                SeqIO.write(res[0][0][1],trimmedReadsR2,'fastq')
            elif res[0][1][0] is not None and res[0][1][1] is not None:
                # If user want to identify primer-dimers
                if idimer and res[2]:
                    r1partSeq=str(res[0][1][0].seq[:40])
                    r2partSeq=revComplement(str(res[0][1][1].seq[:40]))
                    difs=countDifs(r1partSeq,r2partSeq)
                    if sum(difs[0:2])<=int(errNumber):
                        # and len(difs[3])>=len(primersR1_5[res[2][0]])
                        if primersR1_5_names[res[2][0]]+' & '+primersR2_5_names[res[2][1]] not in primerDimers.keys():
                            primerDimers[primersR1_5_names[res[2][0]]+' & '+primersR2_5_names[res[2][1]]]=1
                        else:
                            primerDimers[primersR1_5_names[res[2][0]]+' & '+primersR2_5_names[res[2][1]]]+=1
                    else:
                        SeqIO.write(res[0][1][0],untrimmedReadsR1,'fastq')
                        SeqIO.write(res[0][1][1],untrimmedReadsR2,'fastq')
                else:
                    SeqIO.write(res[0][1][0],untrimmedReadsR1,'fastq')
                    SeqIO.write(res[0][1][1],untrimmedReadsR2,'fastq')
                        
            else:
                print('ERROR: nor the 1st item of function result list or 2nd contains anything')
                print(res)
                exit(0)
        else:
            if res[0][0][0] is not None:
                SeqIO.write(res[0][0][0],trimmedReadsR1,'fastq')
            elif res[0][1][0] is not None:
                SeqIO.write(res[0][1][0],untrimmedReadsR1,'fastq')
            else:
                print('ERROR: item of function result list contains anything')
                print(res)
                exit(0)
    print()
    # primersErrors is a dictionary that contains errors in primers
    if args.primersStatistics:
        primersErrors={}
        # primersErrorsPos is a dictionary that contains statistics about location
        # of errors
        primersErrorsPos={}
        # primersErrorsType is a dictionary that contains statistics about type of error
        primersErrorsType={}
        print('Counting errors...')
        for item in primerErrorQ:
            # If key for this primer has not been created, yet
            if not item[0] in primersErrors.keys():
                # For each primer of each pair we will gather the following values:
                # [(0)number of read pairs,
                # (1)number of primers without errors,
                # (2)number of primers with sequencing errors,
                # (3)number of primers with synthesis errors
                # The first item of list - F
                # The second - R
                primersErrors[item[0]]=[[0,0,0,0],[0,0,0,0]]
                
##          R                           F_reverse_complement
## R1 5'---------________________________---------3'
## R2 5'---------________________________---------3'
##          F                           R_reverse_complement
                
            # Increase number of read pairs
            primersErrors[item[0]][0][0]+=1
            primersErrors[item[0]][1][0]+=1
            # F-primers of pairs
            # The last variant is a case when we have single-end reads and 3' does not contain primer sequence
            if ((not primersFileR1_3 and primersFileR2_5 and item[3][0:3]==(0,0,0)) or
                (primersFileR1_3 and primersFileR2_5 and item[3][0:3]==(0,0,0) and item[2][0:3]==(0,0,0)) or
                (primersFileR1_5 and not primersFileR2_5 and not primersFileR1_3 and not primersFileR2_3)):
                primersErrors[item[0]][0][1]+=1
            # If it was overlapping paired-end reads, we try to check if this is sequencing error
            elif primersFileR1_3 and primersFileR2_5 and primersFileR2_3 and item[2][3]!='' and item[3][3]!='':
                # Rererse complement one of primer sequences
                rev=str(Seq(item[2][3]).reverse_complement())
                a=pairwise2.align.globalms(rev,item[3][3],2,-1,-1.53,-0.1)
                # If found sequences are identical, it's a synthesis error
                if list(a[0][0])==list(a[0][1]):
                    primersErrors[item[0]][0][3]+=1
                    # Now we want to save information about error's location
                    poses,muts=getErrors(primersR2_5[item[0]][1:-1],item[3][3])
                    for p in poses:
                        if p not in primersErrorsPos.keys():
                            primersErrorsPos[p]=1
                        else:
                            primersErrorsPos[p]+=1
                    for m in muts:
                        if m not in primersErrorsType.keys():
                            primersErrorsType[m]=1
                        else:
                            primersErrorsType[m]+=1
                # Else it's a sequencing error
                else:
                    primersErrors[item[0]][0][2]+=1
            # Else we just save it as sequencing error
            else:
                primersErrors[item[0]][0][2]+=1
            # R-primers of pairs
            # For R-primer we always have sequence at least at 5' end of R1
            if ((not primersFileR2_3 and item[1][0:3]==(0,0,0)) or
                (primersFileR2_3 and item[1][0:3]==(0,0,0) and item[4][0:3]==(0,0,0))):
                primersErrors[item[0]][1][1]+=1
            # If it was overlapping paired-end reads, we try to check if this is sequencing error
            elif primersFileR1_3 and primersFileR2_5 and primersFileR2_3 and item[4][3]!='' and item[1][3]!='':
                # Rererse complement one of primer sequences
                rev=str(Seq(item[4][3]).reverse_complement())
                a=pairwise2.align.globalms(rev,item[1][3],2,-1,-1.53,-0.1)
                # If found sequences are identical, it's a synthesis error
                try:
                    if list(a[0][0])==list(a[0][1]):
                        primersErrors[item[0]][1][3]+=1
                        # Now we want to save information about error's location
                        poses,muts=getErrors(primersR1_5[item[0]][1:-1],item[1][3])
                        for p in poses:
                            if p not in primersErrorsPos.keys():
                                primersErrorsPos[p]=1
                            else:
                                primersErrorsPos[p]+=1
                        for m in muts:
                            if m not in primersErrorsType.keys():
                                primersErrorsType[m]=1
                            else:
                                primersErrorsType[m]+=1
                    # Else it's a sequencing error
                    else:
                        primersErrors[item[0]][1][2]+=1
                except IndexError:
                    print('IndexError!',a)
                    print(item)
                    exit(0)
            # Else we just save it as sequencing error
            else:
                primersErrors[item[0]][0][2]+=1
        primersStatistics.write('Primer\tTotal_number_of_reads\tNumber_without_any_errors\t'
                                'Number_with_sequencing_errors\tNumber_with_synthesis_errors\n')
        for key,item in primersErrors.items():
            item[0]=list(map(str,item[0]))
            item[1]=list(map(str,item[1]))
            primersStatistics.write(str(key+1)+'F\t'+'\t'.join(item[0])+'\n')
            primersStatistics.write(str(key+1)+'R\t'+'\t'.join(item[1])+'\n')
        primersStatistics.close()

        primersStatisticsPos.write('Position_in_primer\tNumber_of_mutations\n')
        for key,item in primersErrorsPos.items():
            primersStatisticsPos.write(str(key)+'\t'+str(item)+'\n')
        primersStatisticsPos.close()

        primersStatisticsType.write('Error_type\tNumber_of_mutations\n')
        for key,item in primersErrorsType.items():
            primersStatisticsType.write(str(key)+'\t'+str(item)+'\n')
        primersStatisticsType.close()
    if idimer:
        idimerFile.write('Primer-dimer\tNumber of read pairs\n')
        for key,item in sorted(primerDimers.items(),key=itemgetter(1),reverse=True):
            idimerFile.write(key+'\t'+str(item)+'\n')
        idimerFile.close()

    trimmedReadsR1.close()
    untrimmedReadsR1.close()
    if args.trimmedReadsR2:
        trimmedReadsR2.close()
        untrimmedReadsR2.close()




        
