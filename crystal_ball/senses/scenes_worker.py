"""PySceneDetect worker in its separately configured runtime. JSON on stdout."""
import contextlib
import json
import sys


def detect(req):
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector, AdaptiveDetector, ThresholdDetector
    cfg=req['scenes']
    video=open_video(req['file'])
    try:
        # Threshold means content score (content) or neighbouring-score ratio (adaptive).
        minimum=max(1,round(float(cfg['min_shot_s'])*video.frame_rate))
        detector=(ContentDetector(threshold=float(cfg['threshold']),min_scene_len=minimum) if cfg['detector']=='content' else
                  AdaptiveDetector(adaptive_threshold=float(cfg['threshold']),min_scene_len=minimum))
        manager=SceneManager(); manager.add_detector(detector)
        manager.detect_scenes(video=video,show_progress=False)
        cuts=[start.get_seconds() for start,end in manager.get_scene_list(start_in_scene=True)][1:]
        video.reset()
        manager=SceneManager()
        manager.add_detector(ThresholdDetector(threshold=12,min_scene_len=minimum,add_final_scene=True))
        manager.detect_scenes(video=video,show_progress=False)
        fades=[start.get_seconds() for start,end in manager.get_scene_list(start_in_scene=True)][1:]
        return {'cuts':cuts,'threshold_crossings':fades,'engine':'pyscenedetect'}
    finally:
        # OpenCV's capture is closed when the stream is released.
        if hasattr(video,'close'):
            video.close()


def main():
    req=json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        result=detect(req)
    print(json.dumps(result,allow_nan=False))

if __name__=='__main__':
    main()
