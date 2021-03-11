from airflow.utils.log.logging_mixin import LoggingMixin
from airflow.utils.dates import days_ago
from datetime import timedelta
from airflow.models import DAG
from datetime import datetime
from nnunet.NnUnetOperator import NnUnetOperator
from nnunet.getTasks import get_tasks
from nnunet.GetTaskModelOperator import GetTaskModelOperator
# from nnunet.GetContainerModelOperator import GetContainerModelOperator
from kaapana.operators.DcmConverterOperator import DcmConverterOperator
from kaapana.operators.DcmSendOperator import DcmSendOperator
from kaapana.operators.Itk2DcmSegOperator import Itk2DcmSegOperator
from kaapana.operators.LocalGetInputDataOperator import LocalGetInputDataOperator
from kaapana.operators.LocalWorkflowCleanerOperator import LocalWorkflowCleanerOperator
from airflow.api.common.experimental import pool as pool_api

gpu_count_pool = pool_api.get_pool(name="GPU_COUNT")
gpu_count = int(gpu_count_pool.slots) if gpu_count_pool is not None else 1
max_active_runs = gpu_count

available_pretrained_task_names, installed_tasks, all_selectable_tasks = get_tasks()
ui_forms = {
    "publication_form": {
        "type": "object",
        "properties": {
            "title": {
                "title": "Title",
                "default": "Automated Design of Deep Learning Methods\n for Biomedical Image Segmentation",
                "type": "string",
                "readOnly": True,
            },
            "authors": {
                "title": "Authors",
                "default": "Fabian Isensee, Paul F. Jäger, Simon A. A. Kohl, Jens Petersen, Klaus H. Maier-Hein",
                "type": "string",
                "readOnly": True,
            },
            "link": {
                "title": "DOI",
                "default": "https://arxiv.org/abs/1904.08128",
                "description": "DOI",
                "type": "string",
                "readOnly": True,
            },
            "confirmation": {
                "title": "Accept",
                "default": False,
                "type": "boolean",
                "readOnly": True,
                "required": True,
            }
        }
    },
    "workflow_form": {
        "type": "object",
        "properties": {
            "task": {
                "title": "Tasks available",
                "description": "Select one of the available tasks.",
                "type": "string",
                "enum": sorted(list(all_selectable_tasks.keys())),
                "required": True
            },
            "description": {
                "title": "Task Description",
                "description": "Description of the task.",
                "type": "string",
                "readOnly": True,
                "dependsOn": [
                    "task"
                ]
            },
            "task_url": {
                "title": "Website",
                "description": "Website to the task.",
                "type": "string",
                "readOnly": True,
                "dependsOn": [
                    "task"
                ]
            },
            "input": {
                "title": "Input Modalities",
                "description": "Expected input modalities.",
                "type": "string",
                "readOnly": True,
                "dependsOn": [
                    "task"
                ]
            },
            "body_part": {
                "title": "Body Part",
                "description": "Body part, which needs to be present in the image.",
                "type": "string",
                "readOnly": True,
                "dependsOn": [
                    "task"
                ]
            },
            "targets": {
                "title": "Segmentation Targets",
                "type": "string",
                "readOnly": True,
                "dependsOn": [
                    "task"
                ]
            },
            "model": {
                "title": "Pre-trained models",
                "description": "Select one of the available models.",
                "type": "string",
                "default": "3d_lowres",
                "required": True,
                "enum": [],
                "dependsOn": [
                    "task"
                ]
            },
            "single_execution": {
                "title": "single execution",
                "description": "Should each series be processed separately?",
                "type": "boolean",
                "default": True,
                "readOnly": False,
            }
        }
    }
}
args = {
    'ui_visible': True,
    'ui_dag_info': all_selectable_tasks,
    'ui_forms': ui_forms,
    'owner': 'kaapana',
    'start_date': days_ago(0),
    'retries': 0,
    'retry_delay': timedelta(seconds=60)
}

dag = DAG(
    dag_id='nnunet-predict',
    default_args=args,
    concurrency=10,
    max_active_runs=max_active_runs,
    schedule_interval=None
)

get_input = LocalGetInputDataOperator(
    dag=dag,
    parallel_downloads=5,
    check_modality=True
)
get_task_model = GetTaskModelOperator(dag=dag)
# get_task_model = GetContainerModelOperator(dag=dag)
dcm2nifti = DcmConverterOperator(
    dag=dag,
    input_operator=get_input,
    output_format='nii.gz'
)

nnunet_predict = NnUnetOperator(
    dag=dag,
    mode="inference",
    input_modality_operators=[dcm2nifti],
    inf_preparation=True,
    inf_threads_prep=1,
    inf_threads_nifti=1
)

alg_name = nnunet_predict.image.split("/")[-1].split(":")[0]
nrrd2dcmSeg_multi = Itk2DcmSegOperator(
    dag=dag,
    input_operator=get_input,
    segmentation_operator=nnunet_predict,
    input_type="multi_label_seg",
    multi_label_seg_name=alg_name,
    skip_empty_slices=True,
    alg_name=alg_name
)

dcmseg_send_multi = DcmSendOperator(dag=dag, input_operator=nrrd2dcmSeg_multi)
clean = LocalWorkflowCleanerOperator(dag=dag, clean_workflow_dir=True)

get_input >> get_task_model >> dcm2nifti >> nnunet_predict >> nrrd2dcmSeg_multi >> dcmseg_send_multi >> clean
