import os
import hydra
import platform
from typing import Type, Dict, Optional
from logging import getLogger
from hydra.utils import get_class
from dataclasses import dataclass, MISSING, field
from omegaconf import DictConfig, OmegaConf
from hydra.core.config_store import ConfigStore

from .import_utils import is_torch_available, is_onnxruntime_available, is_openvino_available, is_neural_compressor_available

from optimum.exporters import TasksManager
from optimum.version import __version__ as optimum_version
from transformers import __version__ as transformers_version

try:
    from accelerate import __version__ as accelerate_version
except ImportError:
    accelerate_version = None
try:
    from diffusers import __version__ as diffusers_version
except ImportError:
    diffusers_version = None

import subprocess
from optimum_benchmark.backends.base import Backend
from optimum_benchmark.benchmarks.base import Benchmark
from optimum_benchmark.backends.base import BackendConfig
from optimum_benchmark.benchmarks.inference import InferenceConfig
from optimum_benchmark.benchmarks.inference import BenchmarkConfig
from optimum_benchmark.utils import get_cpu, get_cpu_ram_mb


OmegaConf.register_new_resolver(
    "infer_task",
    lambda model, revision: TasksManager.infer_task_from_model(
        model=model,
        revision=revision,
    ),
)

LOGGER = getLogger("main")


def get_git_revision_hash(path: Optional[str]) -> str:
    if path is None:
        return None
    else:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=path).decode('ascii').strip()

@dataclass
class ExperimentConfig:
    # BACKEND CONFIGURATION
    backend: BackendConfig = MISSING

    # BENCHMARK CONFIGURATION
    benchmark: BenchmarkConfig = MISSING

    # EXPERIMENT CONFIGURATION
    experiment_name: str = MISSING
    # Model name or path (bert-base-uncased, google/vit-base-patch16-224, ...)
    model: str = MISSING
    # Device name or path (cpu, cuda, cuda:0, ...)
    device: str = MISSING
    # task
    task: str = "${infer_task:${model}, ${hub_kwargs.revision}}"

    # ADDITIONAL MODEL CONFIGURATION: Model revision, use_auth_token, trust_remote_code
    hub_kwargs: Dict = field(default_factory=lambda: {
        "revision": "main",
        "cache_dir": None,
        "force_download": False,
        "local_files_only": False,
        "use_auth_token": False,
    })

    # ENVIRONMENT CONFIGURATION
    environment: Dict = field(default_factory=lambda: {
        "optimum_version": optimum_version,
        "transformers_version": transformers_version,
        "transformers_commit": None,
        "accelerate_version": accelerate_version,
        "accelerate_commit": None,
        "diffusers_version": diffusers_version,
        "python_version": platform.python_version(),
        "system": platform.system(),
        "cpu": get_cpu(),
        "cpu_count": os.cpu_count(),
        "cpu_ram_mb": get_cpu_ram_mb(),
    })


# Register configurations
cs = ConfigStore.instance()
cs.store(name="experiment", node=ExperimentConfig)

if is_torch_available():
    from optimum_benchmark.backends.pytorch import PyTorchConfig
    cs.store(group="backend", name="pytorch", node=PyTorchConfig)

if is_onnxruntime_available():
    from optimum_benchmark.backends.onnxruntime import ORTConfig
    cs.store(group="backend", name="onnxruntime", node=ORTConfig)

if is_openvino_available():
    from optimum_benchmark.backends.openvino import OVConfig
    cs.store(group="backend", name="openvino", node=OVConfig)

if is_neural_compressor_available():
    from optimum_benchmark.backends.neural_compressor import INCConfig
    cs.store(group="backend", name="neural_compressor", node=INCConfig)

cs.store(group="benchmark", name="inference", node=InferenceConfig)



@hydra.main(version_base=None)
def run_experiment(experiment: DictConfig) -> None:
    experiment.environment.transformers_commit = get_git_revision_hash(os.getenv("TRANSFORMERS_PATH"))
    experiment.environment.accelerate_commit = get_git_revision_hash(os.getenv("ACCELERATE_PATH"))

    # Save the config
    OmegaConf.save(experiment, "hydra_config.yaml", resolve=True)

    # Allocate requested benchmark
    benchmark_factory: Type[Benchmark] = get_class(experiment.benchmark._target_)
    benchmark: Benchmark = benchmark_factory()
    benchmark.configure(experiment.benchmark)

    # Allocate requested backend
    backend_factory: Type[Backend] = get_class(experiment.backend._target_)
    backend: Backend = backend_factory(
        experiment.model,
        experiment.task,
        experiment.device,
        experiment.hub_kwargs,
    )

    try:
        backend.configure(experiment.backend)
        # Run the benchmark
        benchmark.run(backend)
        # Save the benchmark results
        benchmark.save()
        # clean backend
        backend.clean()

    # log error and traceback
    except Exception as e:
        LOGGER.error("Error during benchmarking: %s", e)
        backend.clean()
        raise e
