$ErrorActionPreference = 'Stop'
$modelDir = Join-Path $PSScriptRoot '..\model'
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
$downloads = @{
  'face_landmarker.task' = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
  'hand_landmarker.task' = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'
  'yolov8s.pt' = 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt'
}
foreach ($name in $downloads.Keys) {
  $destination = Join-Path $modelDir $name
  if (-not (Test-Path -LiteralPath $destination)) {
    Write-Host "Downloading $name"
    Invoke-WebRequest -Uri $downloads[$name] -OutFile $destination
  }
}
