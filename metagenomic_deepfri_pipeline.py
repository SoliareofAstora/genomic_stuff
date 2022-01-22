import json

from Bio import SeqIO

from DeepFRI.deepfrier import Predictor

from CONFIG.RUNTIME_PARAMETERS import MAX_QUERY_CHAIN_LENGTH, DEEPFRI_PROCESSING_MODES
from CONFIG.FOLDER_STRUCTURE import SEQ_ATOMS_DATASET_PATH, ATOMS

from CPP_lib.libAtomDistanceIO import initialize as initialize_cpp_lib
from CPP_lib.libAtomDistanceIO import load_aligned_contact_map

from utils.elapsed_time_logger import ElapsedTimeLogger
from utils.pipeline_utils import select_target_database, load_deepfri_config
from utils.run_mmseqs_search import run_mmseqs_search
from utils.search_alignments import search_alignments
from utils.seq_file_loader import SeqFileLoader


def load_and_verify_data(target_db_name, work_path):
    # selects only one .faa file from work_path directory
    query_files = list(work_path.glob("**/*.faa"))
    assert len(query_files) > 0, f"No query .faa files found in {work_path}"
    query_file = query_files[0]
    if len(query_files) > 1:
        print(f"{work_path} contains more than one .faa file. Only {query_file} will be processed. {query_files[1:]} will be discarded")
    with open(query_file, "r") as f:
        query_seqs = {record.id: record.seq for record in SeqIO.parse(f, "fasta")}
    assert len(query_seqs) > 0, f"{query_file} does not contain protein sequences that SeqIO can parse."

    # filter out proteins that length is over the CONFIG.RUNTIME_PARAMETERS.MAX_QUERY_CHAIN_LENGTH
    proteins_over_max_length = []
    for query_id in list(query_seqs.keys()):
        if len(query_seqs[query_id]) > MAX_QUERY_CHAIN_LENGTH:
            query_seqs.pop(query_id)
            proteins_over_max_length.append(query_id)

    if len(proteins_over_max_length) > 0:
        print(f"Will skip {proteins_over_max_length} due to sequence length over "
              f"CONFIG.RUNTIME_PARAMETERS.MAX_QUERY_CHAIN_LENGTH. "
              f"Protein ids will be saved in metadata_skipped_ids_due_to_max_length.json")
        json.dump(proteins_over_max_length, open('metadata_skipped_ids_due_to_max_length.json', "w"), indent=4,
                  sort_keys=True)
        if len(query_seqs) == 0:
            print(f"All sequences in {query_file} were too long. No sequences will be processed.")

    # select target database
    target_db = select_target_database(target_db_name)
    target_seqs = SeqFileLoader(SEQ_ATOMS_DATASET_PATH / target_db_name)
    print("Target database: ", target_db)

    return query_file, query_seqs, target_db, target_seqs


def metagenomic_deepfri_pipeline(target_db_name, work_path, contact_threshold, generated_contact):
    query_file, query_seqs, target_db, target_seqs = load_and_verify_data(target_db_name, work_path)
    if len(query_seqs) == 0:
        return

    print(f"Running metagenomic_deepfri_pipeline for {len(query_seqs)} sequences")
    timer = ElapsedTimeLogger(work_path / "metadata_runtime.csv")

    mmseqs_search_output = run_mmseqs_search(query_file, target_db, work_path)
    timer.log("mmseqs2")

    # search the best alignment for each sequence pair from mmseqs2 search.
    # If alignment for query_id exists:
    #       aligned target contact map with query sequence will be processed by DeepFRI GCN
    # else:
    #       unaligned query sequences will be processed by CNN
    #
    # format: alignments[query_id] = {target_id, identity, alignment[seqA = query_seq, seqB = target_seq, score, start, end]}
    alignments = search_alignments(query_seqs, mmseqs_search_output, target_seqs, work_path)
    unaligned_queries = query_seqs.keys() - alignments.keys()
    timer.log("alignments")

    if len(alignments) > 0:
        print(f"Using GCN for {len(alignments)} proteins")
    if len(unaligned_queries) > 0:
        print(f"Using CNN for {len(unaligned_queries)} proteins")
    initialize_cpp_lib()
    deepfri_models_config = load_deepfri_config()

    # mf = molecular_function
    # bp = biological_process
    # cc = cellular_component
    # ec = enzyme_commission
    # DEEPFRI_PROCESSING_MODES = ['mf', 'bp', 'cc', 'ec']
    for mode in DEEPFRI_PROCESSING_MODES:
        timer.reset()
        print("Processing mode: ", mode)
        # GCN for queries with aligned contact map
        if len(alignments) > 0:
            output_file = work_path / f"results_gcn_{mode}.csv"
            if output_file.exists():
                print(f"{output_file.name} already exists.")
            else:
                gcn_params = deepfri_models_config["gcn"]["models"][mode]
                gcn = Predictor.Predictor(gcn_params, gcn=True)
                for query_id in alignments.keys():
                    alignment = alignments[query_id]
                    query_seq = query_seqs[query_id]
                    target_id = alignment["target_id"]

                    generated_query_contact_map = load_aligned_contact_map(
                        str(SEQ_ATOMS_DATASET_PATH / target_db_name / ATOMS / (target_id + ".bin")),
                        contact_threshold,
                        alignment["alignment"][0],      # query alignment
                        alignment["alignment"][1],      # target alignment
                        generated_contact)

                    gcn.predict_with_cmap(query_seq, generated_query_contact_map, query_id)

                gcn.export_csv(output_file, verbose=False)
                del gcn
                timer.log(f"deepfri_gcn_{mode}")

        # CNN for queries without satisfying alignments
        if len(unaligned_queries) > 0:
            output_file = work_path / f"results_cnn_{mode}.csv"
            if output_file.exists():
                print(f"{output_file.name} already exists.")
            else:
                cnn_params = deepfri_models_config["cnn"]["models"][mode]
                cnn = Predictor.Predictor(cnn_params, gcn=False)
                for query_id in unaligned_queries:
                    cnn.predict_from_sequence(query_seqs[query_id], query_id)

                cnn.export_csv(output_file, verbose=False)
                del cnn
                timer.log(f"deepfri_cnn_{mode}")

    timer.log_total_time()
