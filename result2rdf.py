import csv
import json
import os
from typing import List, Iterator

import dateutil.parser
import rdflib as rdf

fieldnames = ["starttime", "benchmarkID", "format", "dataset", "triplestore", "noclients", "queryID", "qps",
              "penalizedQps",
              "succeeded", "failed", "timeouts", "unknownExceptions", "wrongCodes", "totaltime", "resultsize",
              "penalizedtime"]


class TaskMetaData:
    def __init__(self, benchmarkID: str, format: str, dataset: str, noclients: int, triplestore: str, starttime: str,
                 runtime: float, QMPH: float, AvgQPS: float, NoQ: float, NoQPH: float):
        self.benchmarkID = str(benchmarkID)
        self.format = str(format)
        self.dataset = str(dataset)
        self.noclients = int(noclients)
        self.triplestore = str(triplestore)
        self.starttime = dateutil.parser.parse(starttime)
        self.runtime = float(runtime)
        self.QMPH = float(QMPH)
        self.AvgQPS = float(AvgQPS)
        self.NoQ = float(NoQ)
        self.NoQPH = float(NoQPH)
        self.PenalizedAvgQPS = None


def extract_meta_data(rdf_graph) -> List[TaskMetaData]:
    raw_tasks = list(rdf_graph.query(
        ''' PREFIX iguanac: <http://iguana-benchmark.eu/class/>
            PREFIX iguana: <http://iguana-benchmark.eu/properties/>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT DISTINCT ?benchmarkID ?format ?dataset ?noclients ?triplestore ?starttime ?runtime ?QMPH ?AvgQPS ?NoQ ?NoQPH WHERE
            {
            ?benchmarkID rdf:type iguanac:Task .
            ?benchmarkID rdfs:startDate ?starttime .
            ?benchmarkID iguana:timeLimit ?runtime.
            # experiment
            ?experiment iguana:task ?benchmarkID .
            ?experiment iguana:dataset ?ds.
            ?ds rdfs:label ?dataset.
            # triplestore label
            ?benchmarkID iguana:connection ?conn .
            ?conn rdfs:label ?triplestore.
            # clients
            ?benchmarkID iguana:noOfWorkers ?noclients .
            # worker results
            ?benchmarkID iguana:workerResult ?wr .
            ?wr iguana:workerType ?workerType .
            BIND( IF(CONTAINS(?workerType, "CLI"),"CLI","HTTP") AS ?format )
            # metrics
            ?benchmarkID iguana:QMPH ?QMPH ; 
                         iguana:AvgQPS ?AvgQPS ; 
                         iguana:NoQ ?NoQ ;
                         iguana:NoQPH ?NoQPH .
            } '''
    ))
    return [TaskMetaData(**raw_task.asdict()) for raw_task in raw_tasks]


def convert_result_file(rdf_file: str, input_dir: str, output_dir: str) -> Iterator[str]:
    """
    Converts a input file
    :param rdf_file: the IGUANA output file to be processed
    :return: the file where the result was written to
    """

    # load the file
    iguana_result_graph = rdf.Graph()
    iguana_result_graph.parse(os.path.join(input_dir, rdf_file), format="nt")

    tasks_meta_data: List[TaskMetaData] = extract_meta_data(iguana_result_graph)

    for task_meta_data in tasks_meta_data:

        query_results = iguana_result_graph.query(
            ''' PREFIX iguanac: <http://iguana-benchmark.eu/class/>
                PREFIX iguana: <http://iguana-benchmark.eu/properties/>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                SELECT ?starttime ?benchmarkID ?format ?dataset ?triplestore ?noclients ?queryID ?qps ?penalizedQPS ?succeeded ?failed ?timeouts ?unknownExceptions ?wrongCodes ?totaltime ?resultsize WHERE
                {{
                BIND( {benchmarkID} AS ?benchmarkID )
                {benchmarkID} rdf:type iguanac:Task .
                {benchmarkID} rdfs:startDate ?starttime .
                # experiment
                ?experiment iguana:task {benchmarkID} .
                ?experiment iguana:dataset ?ds.
                ?ds rdfs:label ?dataset.
                # triplestore label
                {benchmarkID} iguana:connection ?conn .
                ?conn rdfs:label ?triplestore.
                # clients
                {benchmarkID} iguana:noOfWorkers ?noclients .
                # worker results
                {benchmarkID} iguana:workerResult ?wr .
                ?wr iguana:query ?queryIDURI.
                ?queryIDURI iguana:queryID ?queryID .
                ?queryIDURI iguana:QPS ?qps.
                ?queryIDURI iguana:penalizedQPS ?penalizedQPS.
                ?queryIDURI iguana:succeeded ?succeeded.
                ?queryIDURI iguana:failed ?failed.
                ?queryIDURI iguana:timeOuts ?timeouts.
                ?queryIDURI iguana:unknownException ?unknownExceptions.
                ?queryIDURI iguana:wrongCodes ?wrongCodes.
                ?queryIDURI iguana:totalTime ?totaltime.
                ?queryIDURI iguana:resultSize ?resultsize.
                BIND( "{bindformat}" AS ?format )
                }} '''.format(benchmarkID="<{}>".format(task_meta_data.benchmarkID), bindformat=task_meta_data.format)
        )

        outputfile: str = "{}_{}_{:02d}-clients_{}_{}".format(task_meta_data.format, task_meta_data.dataset,
                                                              int(task_meta_data.noclients), task_meta_data.triplestore,
                                                              task_meta_data.starttime.strftime("%Y-%m-%d_%H-%M-%S"))
        os.makedirs(output_dir, exist_ok=True)

        task_meta_data.PenalizedAvgQPS = 0

        output_csv = os.path.join(output_dir, outputfile + ".csv")
        with open(output_csv, 'w') as csvfile:
            csvwriter = csv.DictWriter(csvfile,
                                       fieldnames=fieldnames,
                                       quoting=csv.QUOTE_NONNUMERIC)
            csvwriter.writeheader()
            for binding in sorted(list(query_results), key=lambda x: x.queryID):
                # TODO: make penalty time configurable
                penalty_time = 180000

                task_meta_data.PenalizedAvgQPS += float(binding.penalizedQPS)

                penalized_time = float(binding.totaltime)
                if int(binding.failed) > 0 and float(binding.totaltime) < penalty_time * int(binding.failed):
                    penalized_time = penalized_time + penalty_time * int(binding.failed)

                csvwriter.writerow({
                    "starttime": binding.starttime,
                    "benchmarkID": binding.benchmarkID,
                    "format": binding.format,
                    "dataset": binding.dataset,
                    "triplestore": binding.triplestore,
                    "noclients": int(binding.noclients),
                    "queryID": binding.queryID,
                    "qps": binding.qps,
                    "penalizedQps": float(binding.penalizedQPS),
                    "succeeded": int(binding.succeeded),
                    "failed": int(binding.failed),
                    "wrongCodes": int(binding.wrongCodes),
                    "unknownExceptions": int(binding.unknownExceptions),
                    "timeouts": int(binding.timeouts),
                    "totaltime": float(binding.totaltime),
                    "resultsize": int(binding["resultsize"]) if str(binding["resultsize"]) != '?' else '',
                    "penalizedtime": penalized_time
                })
        task_meta_data.PenalizedAvgQPS = task_meta_data.PenalizedAvgQPS / len(query_results) if task_meta_data.PenalizedAvgQPS > 0 else 0


        with open(os.path.join(output_dir, outputfile + ".json"), "w") as jsonfile:
            jsonfile.write(json.dumps({'benchmarkID': task_meta_data.benchmarkID,
                                       'triplestore': task_meta_data.triplestore,
                                       'dataset': task_meta_data.dataset,
                                       'starttime': str(task_meta_data.starttime),
                                       'runtime': task_meta_data.runtime,
                                       "format": task_meta_data.format,
                                       'noclients': task_meta_data.noclients,
                                       'QMPH': task_meta_data.QMPH,
                                       'AvgQPS': task_meta_data.AvgQPS,
                                       'PenalizedAvgQPS': task_meta_data.PenalizedAvgQPS,
                                       'NoQ': task_meta_data.NoQ,
                                       'NoQPH': task_meta_data.NoQPH,
                                       },
                                      sort_keys=True,
                                      indent=4),
                           )
        yield os.path.join(output_dir, outputfile)
