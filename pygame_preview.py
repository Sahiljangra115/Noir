import numpy as np

def require_pygame():
    try:
        import pygame
        return pygame
    except ImportError as e:
        raise ImportError(
            "pygame is required for this operation. "
            "Install it with 'pip install pygame' or use a mode that does not require pygame."
        ) from e


def pygame_bgr_preview(image_bgr: np.ndarray, window_name="ML Line Tracking"):
    """
    Display a numpy BGR image in a pygame window. Handles quit/key events:
    'q'=quit, 'p'=pause, 'd'=debug, 'l'=line overlay. Returns flag dictionary.
    """
    pygame = require_pygame()
    import cv2

    img_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    h, w = img_rgb.shape[:2]
    control_flags = {'quit': False, 'pause': False, 'debug': False, 'line': False}

    if not pygame.get_init():
        pygame.init()
        pygame.display.set_caption(window_name)
        _pygame_bgr_preview_state['surface'] = pygame.display.set_mode((w, h))
    surface = _pygame_bgr_preview_state.get('surface')
    if surface is None or surface.get_size() != (w, h):
        surface = pygame.display.set_mode((w, h))
        _pygame_bgr_preview_state['surface'] = surface

    surf_img = pygame.surfarray.make_surface(np.transpose(img_rgb, (1, 0, 2)))
    surface.blit(surf_img, (0, 0))
    pygame.display.flip()
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            control_flags['quit'] = True
        elif event.type == pygame.KEYDOWN:
            k = event.unicode.lower()
            if k == 'q':
                control_flags['quit'] = True
            elif k == 'p':
                control_flags['pause'] = True
            elif k == 'd':
                control_flags['debug'] = True
            elif k == 'l':
                control_flags['line'] = True
    return control_flags

# Module-level singleton state for surface.
_pygame_bgr_preview_state = {}